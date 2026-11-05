import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

const API = "http://127.0.0.1:8099";

async function newToken(page: Page): Promise<string> {
  await page.goto("/devices");
  await page.getByLabel("Nome (ex.: piloto TI)").fill("sensores e2e");
  await page.getByRole("button", { name: "Criar token" }).click();
  const token = (await page.getByTestId("new-token").textContent())!.trim();
  await page.getByRole("button", { name: "Já guardei" }).click();
  return token;
}

async function send(page: Page, key: string, app: string, text: string, user = "pessoa.simulada@empresa-exemplo.com.br") {
  const r = await page.request.post(`${API}/v1/events`, {
    headers: { "X-API-Key": key },
    data: {
      event_id: crypto.randomUUID(), occurred_at: new Date().toISOString(),
      source: { channel: app.endsWith("_web") ? "browser" : "agent_hook", app, integration_status: "experimental" },
      actor: { user_id: user }, kind: "prompt", content: { text },
      context: { session_id: "s1", personal_account: false },
    },
  });
  expect(r.status()).toBe(200);
}

test("sensores: hostname, IAs habilitadas por máquina, evidência de captura, filtros e detalhe", async ({ page }) => {
  await login(page, USERS.admin);
  const token = await newToken(page);
  const enroll = async (hostname: string, ias: string[], tools: string[], version = "0.1") => {
    const r = await page.request.post(`${API}/v1/enroll`, { data: { token, hostname, os: "Windows", client_version: version, tools, ias } });
    expect(r.status()).toBe(201);
    return (await r.json()).api_key as string;
  };
  const keyAna = await enroll("SENS-E2E-ANA", ["chatgpt_web", "claude_code", "codex_cli"], ["claude_code", "browser_extension"], "9.9");   // a versão mais nova da frota
  await enroll("SENS-E2E-BRUNO", ["gemini_web"], ["browser_extension"]);
  await enroll("SENS-E2E-LEGADO", [], ["claude_code"]);              // sensor antigo: não informou as IAs
  await send(page, keyAna, "chatgpt_web", "SIMULADO: oi do navegador");
  await send(page, keyAna, "claude_code", "SIMULADO: oi do terminal", "outra.pessoa@empresa-exemplo.com.br");   // máquina com duas pessoas

  await page.goto("/sensors");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sensores");
  await page.getByLabel("Nome da máquina").fill("SENS-E2E");
  const rows = page.getByTestId("sensor-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("SENS-E2E-ANA");                                 // hostname aparece
  const ana = page.getByRole("row", { name: /SENS-E2E-ANA/ });
  await expect(ana.getByTestId("ia-chip").filter({ hasText: "ChatGPT (web)" })).toContainText("capturando");
  await expect(ana.getByTestId("ia-chip").filter({ hasText: "Claude Code (CLI)" })).toContainText("capturando");
  await expect(ana.getByTestId("ia-chip").filter({ hasText: "Codex (CLI)" })).toContainText("aguardando");   // instalado, mas sem evento: não finge
  const bruno = page.getByRole("row", { name: /SENS-E2E-BRUNO/ });
  await expect(bruno.getByTestId("ia-chip")).toContainText("Gemini (web) · aguardando evento");           // habilitada, mas sem evento ainda
  await expect(page.getByRole("row", { name: /SENS-E2E-LEGADO/ })).toContainText("não informado");
  await expect(page.getByTestId("sem-ias")).toContainText("1 sensor");

  // último usuário (calculado dos eventos) e quantas pessoas usaram a máquina
  await expect(ana.getByTestId("last-user")).toContainText("outra.pessoa@empresa-exemplo.com.br");
  await expect(ana.getByTestId("last-user")).toContainText("+1 pessoa(s) em 30 dias");
  await expect(bruno.getByTestId("last-user")).toContainText("sem eventos em 30 dias");

  // alertas: Bruno e o legado estão na 0.1 e a frota tem a 9.9; a Ana está em dia
  await expect(bruno.getByTestId("alerta")).toContainText("Sensor desatualizado");
  await expect(bruno).toContainText("desatualizado");
  await expect(ana.getByTestId("alerta")).toHaveCount(0);
  await page.getByLabel("Alertas", { exact: true }).selectOption("qualquer");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "SENS-E2E-ANA" })).toHaveCount(0);
  await expect(page.getByTestId("alertas")).toContainText("Sensor desatualizado");
  await page.getByLabel("Alertas", { exact: true }).selectOption("");
  await expect(rows).toHaveCount(3);

  // exportação CSV auditada, com os mesmos filtros do painel
  await expect(page.getByTestId("export-sensors")).toBeVisible();
  const href = (await page.getByTestId("export-sensors").getAttribute("href"))!;
  expect(href).toContain("q=SENS-E2E");
  const csv = await page.request.get(href);
  expect(csv.status()).toBe(200);
  const text = await csv.text();
  expect(text).toContain("maquina,sistema,versao_sensor,situacao");
  expect(text).toContain("SENS-E2E-ANA");
  expect(text).toContain("outra.pessoa@empresa-exemplo.com.br");
  expect(text).toContain("chatgpt_web;claude_code;codex_cli");

  // filtro por IA habilitada
  await page.getByLabel("IA habilitada").selectOption("gemini_web");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("SENS-E2E-BRUNO");
  await page.getByRole("button", { name: "Limpar filtros" }).click();
  await page.getByLabel("Nome da máquina").fill("legado");                                  // sem diferenciar maiúsculas
  await expect(rows).toHaveCount(1);
  await page.getByLabel("Nome da máquina").fill("SENS-E2E-ANA");

  // detalhe: eventos por IA
  await page.getByRole("button", { name: "Ver detalhes da máquina SENS-E2E-ANA" }).click();
  const detail = page.getByTestId("sensor-detail");
  await expect(detail).toContainText("SENS-E2E-ANA");
  const chat = detail.getByTestId("ia-detail").getByRole("row", { name: /ChatGPT \(web\)/ });
  await expect(chat).toContainText("extensão do navegador");
  await expect(chat).toContainText("capturando");
  await expect(chat.getByRole("cell").nth(3)).toHaveText("1");                              // 1 evento nos últimos 7 dias
  await expect(detail.getByTestId("ia-detail").getByRole("row", { name: /Codex \(CLI\)/ })).toContainText("automática");
  await expect(detail.getByTestId("detail-alertas")).toHaveCount(0);                      // a Ana não tem alerta
  await expectAccessible(page);

  // atalho: os prompts só deste sensor
  await detail.getByTestId("ver-prompts").click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Todos os prompts");
  await expect(page.getByTestId("sensor-chip")).toContainText("SENS-E2E-ANA");
  const prompts = page.getByTestId("history-row");
  await expect(prompts).toHaveCount(2);                                                     // só os 2 eventos desse sensor, de pessoas diferentes
  await expect(prompts.filter({ hasText: "SIMULADO: oi do navegador" })).toHaveCount(1);
  await expect(prompts.filter({ hasText: "SIMULADO: oi do terminal" })).toHaveCount(1);
  await page.getByRole("button", { name: "Ver todos" }).click();
  await expect(page.getByTestId("sensor-chip")).toHaveCount(0);
  await page.goto("/sensors");
  await page.getByLabel("Nome da máquina").fill("SENS-E2E-ANA");

  // revogar sai do total de "instalados" e entra em "revogados"
  const installed = page.getByTestId("sensor-kpis").getByTestId("kpi").filter({ hasText: "Sensores instalados" });
  const before = Number((await installed.locator(".font-mono").textContent())!.trim());
  await page.getByRole("button", { name: "Ver detalhes da máquina SENS-E2E-ANA" }).click();
  page.once("dialog", (d) => void d.accept());
  await page.getByTestId("sensor-detail").getByRole("button", { name: "Revogar" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Máquina revogada." })).toBeVisible();
  await expect(installed.locator(".font-mono")).toHaveText(String(before - 1));
});

test("sensores: leitura vê o painel mas não revoga; tema escuro e tablet sem rolagem horizontal da página", async ({ page }) => {
  await login(page, USERS.leitura);
  await page.goto("/sensors");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sensores");
  await expect(page.getByTestId("sensor-kpis")).toBeVisible();
  await expect(page.getByTestId("export-sensors")).toHaveCount(0);                             // leitura não exporta
  const first = page.getByTestId("sensor-row").first();
  if (await first.count()) {
    await first.getByRole("button").first().click();
    await expect(page.getByTestId("sensor-detail")).toBeVisible();
    await expect(page.getByTestId("sensor-detail").getByRole("button", { name: "Revogar" })).toHaveCount(0);
    await page.getByRole("button", { name: "Fechar" }).first().click();
  }
  await page.setViewportSize({ width: 768, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await expectAccessible(page);
});
