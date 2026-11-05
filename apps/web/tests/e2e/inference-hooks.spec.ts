import { createHmac, randomBytes } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { apiGet, expectAccessible, formAlert, login, logout, USERS } from "./helpers";

const API = "http://127.0.0.1:8099";
const WEB = "http://127.0.0.1:3099";
const SECRET = "whsec_" + randomBytes(32).toString("base64");
const AWS = "AKIA" + "Z7QW4XK2M9PLR3TN"; // chave sintética

/** Assina como a Anthropic: HMAC-SHA256 de "{id}.{timestamp}.{corpo}" com a chave decodificada em base64 padrão. */
async function hookCall(apiKey: string, body: object, secret = SECRET) {
  const raw = JSON.stringify(body);
  const id = `req_${randomBytes(6).toString("hex")}`;
  const ts = Math.floor(Date.now() / 1000);
  const sig = "v1," + createHmac("sha256", Buffer.from(secret.replace("whsec_", ""), "base64")).update(`${id}.${ts}.${raw}`).digest("base64");
  const r = await fetch(`${API}/v1/inference-hook`, {
    method: "POST", body: raw,
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey, "webhook-id": id, "webhook-timestamp": String(ts), "webhook-signature": sig },
  });
  return { status: r.status, json: (await r.json()) as { action?: string; deny_reason?: string; reference_id?: string } };
}

async function setSecretPolicy(page: Page, mode: "monitor" | "enforce") {
  const all = (await apiGet<Record<string, unknown>[]>(page, "v1/policies")).data;
  const p = all.find((x) => x.name === "Bloquear segredos e chaves")!;
  const { name, description, enabled, scope, match, action } = p;
  await mutate(page, "PUT", `v1/policies/${p.id as string}`, { name, description, enabled, scope, match, action, mode });
}

const frame = (text: string, session: string) => ({
  type: "prompt", request_id: "ignorado-o-webhook-id-vale", tenant_id: "11111111-1111-1111-1111-111111111111",
  actor: { type: "user", id: "user_e2e", email_address: "alice@example.com" }, source: { application: "claude-ai" }, session_id: session,
  model: "claude-sonnet-4-5", messages: [{ role: "user", content: [{ type: "text", text }] }], metadata: {},
});

async function mutate(page: Page, method: "POST" | "PUT", path: string, data: unknown) {
  const r = await page.request.fetch(`/api/proxy/${path}`, { method, data, headers: { "X-Requested-With": "promptshield", Origin: WEB, "Content-Type": "application/json" } });
  expect(r.ok(), `${method} ${path} -> ${r.status()}`).toBeTruthy();
  return r.json();
}

test("inference hooks: configurar, receber frames assinados, sombra e aplicar, números na tela", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/inference-hooks");
  await expect(page.getByTestId("hook-status")).toContainText("PARCIAL");
  await expect(page.getByTestId("hook-status")).toContainText("nunca foi chamado por um tenant Claude Enterprise de verdade");
  await expect(page.getByTestId("secret-state")).toContainText("Nenhum segredo configurado");

  await page.getByRole("radio", { name: /Aplicar/ }).click();                    // sem segredo, aplicar é recusado
  await expect(formAlert(page)).toContainText("configure o segredo de assinatura");

  await page.getByLabel(/Cole o segredo/).fill("whsec_isto-nao-e-base64!!");
  await page.getByRole("button", { name: "Guardar segredo" }).click();
  await expect(formAlert(page)).toContainText("segredo inválido");
  await page.getByLabel(/Cole o segredo/).fill(SECRET);
  await page.getByRole("button", { name: "Guardar segredo" }).click();
  await expect(page.getByTestId("secret-state")).toContainText("Segredo configurado.");
  await expect(page.getByLabel(/Cole o segredo/)).toHaveValue("");               // o segredo não fica na tela

  const key = (await mutate(page, "POST", "v1/api-keys", { name: "inference hook (teste e2e)" })).key as string;
  expect((await hookCall(key, frame("oi", "s0"), "whsec_" + randomBytes(32).toString("base64"))).status).toBe(401);   // segredo errado
  const shadow = await hookCall(key, frame(`a chave de deploy é ${AWS}`, "s1"));
  expect(shadow).toEqual({ status: 200, json: { action: "allow" } });              // padrão: sombra

  const events = (await apiGet<{ app: string; channel?: string; masked_text: string; would_decide: string; decision: string }[]>(page, "v1/events?app=claude_ai")).data;
  expect(events.length).toBe(1);
  expect(events[0].masked_text).not.toContain(AWS);
  expect([events[0].decision, events[0].would_decide]).toEqual(["allow", "block"]); // política em monitorar: grava o que teria feito

  await setSecretPolicy(page, "enforce");
  await page.reload();
  await page.getByRole("radio", { name: /Aplicar/ }).click();
  await expect(page.getByRole("status")).toHaveText("Configuração salva.");

  const denied = await hookCall(key, frame(`outra chave ${AWS}`, "s2"));
  expect(denied.status).toBe(200);
  expect(denied.json.action).toBe("deny");
  expect(denied.json.deny_reason).toContain("segredo");
  expect(denied.json.deny_reason).not.toContain(AWS);
  expect(denied.json.reference_id).toMatch(/^ps:[0-9a-f]{32}$/);
  const unknownType = await hookCall(key, { ...frame("x", "s3"), type: "response" });
  expect(unknownType.json).toEqual({ action: "allow" });                           // tipo futuro: permitir, nunca erro

  await page.reload();
  const kpi = (label: string) => page.getByTestId("kpi").filter({ hasText: label }).locator("div").first();
  const cfg = (await apiGet<{ stats_24h: { requests: number; denied: number; would_deny: number; p95_ms: number } }>(page, "v1/inference-hook/config")).data;
  expect(cfg.stats_24h.requests).toBe(3);
  expect(cfg.stats_24h.denied).toBe(1);
  await expect(kpi("Requisições (24 h)")).toHaveText("3");
  await expect(kpi("Negadas")).toHaveText("1");
  await expect(kpi("p95 do nosso tempo")).toHaveText(`${cfg.stats_24h.p95_ms} ms`);

  await expectAccessible(page, "/inference-hooks");
  await page.getByRole("radio", { name: /Sombra/ }).click();                         // volta ao padrão seguro
  await expect(page.getByRole("status")).toHaveText("Configuração salva.");
  await setSecretPolicy(page, "monitor");
});

test("inference hooks: analista vê, mas não altera; leitura não vê", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/inference-hooks");
  await expect(page.getByText("Só o administrador altera a configuração.")).toBeVisible();
  await expect(page.getByRole("radio", { name: /Aplicar/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /segredo/i })).toHaveCount(0);
  await logout(page);
  await login(page, USERS.leitura);
  await page.goto("/inference-hooks");
  await expect(page.getByText(/exige papel/)).toBeVisible();
});
