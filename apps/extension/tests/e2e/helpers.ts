import { chromium, type BrowserContext, type Page, type Worker } from "@playwright/test";
import { createServer, type IncomingMessage, type Server } from "node:http";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

export const DEV_DIST = resolve(import.meta.dirname, "../../dist/dev");
const FIXTURES = resolve(import.meta.dirname, "fixtures");

export type Mode = "allow" | "alert" | "mask" | "block" | "ask_justification";
export interface Recorded { path: string; method: string; headers: Record<string, string | string[] | undefined>; body: any }

/** API simulada com o mesmo formato de resposta da API real (POST /v1/events). Responde CORS como a API real. */
export class MockApi {
  server!: Server;
  port = 0;
  mode: Mode = "allow";
  stopped = false;   // simula a licença/contrato que parou a inspeção
  requests: Recorded[] = [];
  remote = { failure_mode: "open", domains: ["127.0.0.1", "localhost"], policy_url: "https://intranet.exemplo.test/politica-ia" };

  async start(): Promise<this> {
    this.server = createServer(async (req, res) => {
      const origin = String(req.headers.origin ?? "");
      if (origin.startsWith("chrome-extension://")) {   // a API real só libera a origem da extensão
        res.setHeader("Access-Control-Allow-Origin", origin);
        res.setHeader("Access-Control-Allow-Headers", "X-API-Key, Content-Type");
        res.setHeader("Access-Control-Allow-Methods", "GET, POST");
        res.setHeader("Vary", "Origin");
      }
      const url = new URL(req.url ?? "/", "http://x");
      if (req.method === "OPTIONS") { res.writeHead(204).end(); return; }
      if (url.pathname.endsWith(".html")) {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(readFileSync(join(FIXTURES, url.pathname)));
        return;
      }
      const body = await readBody(req);
      this.requests.push({ path: url.pathname, method: req.method ?? "", headers: req.headers, body });
      if (req.headers["x-api-key"] !== "ps_test_key") { res.writeHead(401).end("{}"); return; }
      if (this.stopped && url.pathname === "/v1/events") {
        res.writeHead(403, { "Content-Type": "application/json", "X-PromptShield-Inspection": "stopped", "Access-Control-Expose-Headers": "X-PromptShield-Inspection" })
          .end(JSON.stringify({ detail: "inspeção parada" }));
        return;
      }
      if (url.pathname === "/v1/events" && req.method === "POST") {
        const text: string = body.content.text;
        const hasCpf = /\d{3}\.\d{3}\.\d{3}-\d{2}/.test(text);
        const masked = text.replace(/(\d{3}\.\d{3}\.\d{3}-)(\d{2})/g, "***.***.***-$2");
        const decision: Mode = hasCpf ? this.mode : "allow";
        res.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify({
          event_id: body.event_id, decision, would_decide: hasCpf ? this.mode : "allow", masked_text: masked,
          categories: hasCpf ? [{ id: "pii", confidence: 0.97 }] : [], risk: { score: hasCpf ? 58 : 0 },
        }));
        return;
      }
      if (url.pathname.endsWith("/justification")) { res.writeHead(204).end(); return; }
      if (url.pathname === "/v1/extension-config") { res.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify(this.remote)); return; }
      res.writeHead(404).end("{}");
    });
    await new Promise<void>((ok) => this.server.listen(0, "127.0.0.1", ok));
    this.port = (this.server.address() as { port: number }).port;
    return this;
  }
  get url() { return `http://127.0.0.1:${this.port}`; }
  get events() { return this.requests.filter((r) => r.path === "/v1/events" && r.method === "POST"); }
  async stop() { await new Promise((ok) => this.server.close(ok)); }
}

function readBody(req: IncomingMessage): Promise<any> {
  return new Promise((ok) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => { try { ok(JSON.parse(Buffer.concat(chunks).toString() || "null")); } catch { ok(null); } });
  });
}

export interface Launched { ctx: BrowserContext; sw: Worker }

/** Abre o Chromium com a extensão de desenvolvimento e grava a configuração local (equivale à política gerenciada). */
export async function launchWithExtension(devConfig: Record<string, unknown>): Promise<Launched> {
  const userData = mkdtempSync(join(tmpdir(), "ps-ext-"));
  const ctx = await chromium.launchPersistentContext(userData, {
    executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: false,
    args: ["--headless=new", "--no-sandbox", `--disable-extensions-except=${DEV_DIST}`, `--load-extension=${DEV_DIST}`],
  });
  const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker"));
  await sw.evaluate((cfg) => chrome.storage.local.set({ devConfig: cfg }), devConfig);
  return { ctx, sw };
}

export async function typeAndSubmit(page: Page, text: string, how: "enter" | "click" = "enter") {
  const field = page.locator("#prompt");
  await field.click();
  await page.keyboard.insertText(text);
  if (how === "enter") await page.keyboard.press("Enter");
  else await page.locator("#send").click();
}

export const sent = (page: Page): Promise<string[]> => page.evaluate(() => (window as any).__sent as string[]);

/** O indicador e os diálogos ficam em shadow DOM fechado; o Playwright atravessa shadow roots (inclusive fechados) em locators. */
export const ui = (page: Page) => page.locator("promptshield-ui");
