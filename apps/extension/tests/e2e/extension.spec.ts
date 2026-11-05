import { expect, test, type Page } from "@playwright/test";
import { launchWithExtension, MockApi, sent, typeAndSubmit, ui, type Launched } from "./helpers";

const CPF = "529.982.247-25";
const PROMPT = `Cliente ${CPF}, pode revisar o contrato?`;
const MASKED = "Cliente ***.***.***-25, pode revisar o contrato?";

let api: MockApi;
let L: Launched | undefined;

const config = (over: Record<string, unknown> = {}) => ({
  api_url: api.url, api_key: "ps_test_key", user_id: "rafael.moreira", department: "Engenharia",
  domains: ["127.0.0.1"], policy_url: "https://intranet.exemplo.test/politica-ia", fail_mode: "open", timeout_ms: 1500, ...over,
});

async function open(over: Record<string, unknown> = {}, path = "/chat.html"): Promise<Page> {
  L = await launchWithExtension(config(over));
  const page = await L.ctx.newPage();
  await page.goto(`${api.url}${path}`);
  return page;
}

test.beforeEach(async () => { api = await new MockApi().start(); });
test.afterEach(async () => { await L?.ctx.close(); L = undefined; await api.stop(); });

test("indicador de monitoramento visível, com link da política", async () => {
  const page = await open();
  const pill = ui(page).locator(".pill");
  await expect(pill).toBeVisible();
  await expect(pill).toContainText("monitoramento ativo");
  await expect(ui(page).locator("a")).toHaveAttribute("href", "https://intranet.exemplo.test/politica-ia");
});

test("o aviso pode ser minimizado (continua visível como ponto) e expandido de novo", async () => {
  const page = await open();
  const pill = ui(page).locator(".pill");
  await ui(page).getByRole("button", { name: "Minimizar o aviso do PromptShield" }).click();
  await expect(pill).toHaveAttribute("data-min", "1");
  await expect(pill).toBeVisible();
  await expect(ui(page).getByText("monitoramento ativo")).toBeHidden();    // o texto some, o ponto fica
  await ui(page).getByRole("button", { name: "Expandir o aviso do PromptShield" }).click();
  await expect(ui(page).getByText("monitoramento ativo")).toBeVisible();
  await page.mouse.click(400, 300);    // clicar fora também minimiza
  await expect(pill).toHaveAttribute("data-min", "1");
  await expect(pill).toBeVisible();
});

test("CPF sintético: pede confirmação e envia a versão mascarada", async () => {
  api.mode = "mask";
  const page = await open();
  await typeAndSubmit(page, PROMPT);
  const dlg = ui(page).locator('[role="dialog"]');
  await expect(dlg).toContainText("dados pessoais");
  await expect(dlg.locator("pre")).toHaveText(MASKED);
  expect(await sent(page)).toEqual([]);                       // nada foi enviado antes da confirmação
  await dlg.getByRole("button", { name: "Enviar versão mascarada" }).click();
  await expect.poll(() => sent(page)).toEqual([MASKED]);      // o site só recebeu o texto mascarado
  expect(JSON.stringify(await sent(page))).not.toContain(CPF);
  expect(api.events).toHaveLength(1);
  const ev = api.events[0].body;
  expect(ev).toMatchObject({ kind: "prompt", source: { channel: "browser", app: "chatgpt_web", integration_status: "partial" },
    actor: { user_id: "rafael.moreira", department: "Engenharia" }, content: { text: PROMPT }, context: { personal_account: false } });
});

test("bloqueio por política: nada é enviado e o texto fica no campo", async () => {
  api.mode = "block";
  const page = await open();
  await typeAndSubmit(page, PROMPT);
  const dlg = ui(page).locator('[role="dialog"]');
  await expect(dlg).toContainText("Envio bloqueado");
  await dlg.getByRole("button", { name: "Entendi" }).click();
  expect(await sent(page)).toEqual([]);
  await expect(page.locator("#prompt")).toContainText("Cliente");
});

test("política em monitorar (allow): envia o original sem diálogo, por Enter e por clique", async () => {
  api.mode = "allow";
  const page = await open();
  await typeAndSubmit(page, PROMPT, "enter");
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  await typeAndSubmit(page, "outro prompt sem dados", "click");
  await expect.poll(() => sent(page)).toEqual([PROMPT, "outro prompt sem dados"]);
  await expect(ui(page).locator('[role="dialog"]')).toHaveCount(0);
  expect(api.events).toHaveLength(2);
});

test("pedir justificativa: exige 10 caracteres, registra e envia o original", async () => {
  api.mode = "ask_justification";
  const page = await open();
  await typeAndSubmit(page, PROMPT);
  const dlg = ui(page).locator('[role="dialog"]');
  const ok = dlg.getByRole("button", { name: "Enviar com justificativa" });
  await expect(ok).toBeDisabled();
  await dlg.getByLabel("Justificativa").fill("curto");
  await expect(ok).toBeDisabled();
  await dlg.getByLabel("Justificativa").fill("preciso enviar ao cliente hoje");
  await ok.click();
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  const j = api.requests.find((r) => r.path.endsWith("/justification"));
  expect(j?.body).toEqual({ justification: "preciso enviar ao cliente hoje" });
});

test("aviso antes do envio (alert): cancelar mantém o prompt, confirmar envia", async () => {
  api.mode = "alert";
  const page = await open();
  await typeAndSubmit(page, PROMPT);
  const dlg = ui(page).locator('[role="dialog"]');
  await expect(dlg).toContainText("Atenção");
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
  expect(await sent(page)).toEqual([]);
  await page.locator("#prompt").click();
  await page.keyboard.press("Enter");
  await ui(page).locator('[role="dialog"]').getByRole("button", { name: "Enviar mesmo assim" }).click();
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
});

test("campo textarea também é mascarado", async () => {
  api.mode = "mask";
  const page = await open({}, "/chat-textarea.html");
  await page.locator("#prompt").fill(PROMPT);
  await page.keyboard.press("Enter");
  await ui(page).locator('[role="dialog"]').getByRole("button", { name: "Enviar versão mascarada" }).click();
  await expect.poll(() => sent(page)).toEqual([MASKED]);
});

test("nunca lê tecla por tecla: nada vai à API até o envio", async () => {
  const page = await open();
  await page.locator("#prompt").click();
  await page.keyboard.type(`digitando devagar o CPF ${CPF}`, { delay: 15 });
  await page.waitForTimeout(400);
  expect(api.events).toHaveLength(0);
  expect(api.requests.filter((r) => r.path === "/v1/events")).toHaveLength(0);
});

test("fora dos domínios configurados: sem indicador e sem nenhuma chamada à API", async () => {
  api.mode = "block";
  L = await launchWithExtension(config());                         // domains = ["127.0.0.1"]
  const page = await L.ctx.newPage();
  await page.goto(`http://localhost:${api.port}/chat.html`);        // mesmo servidor, outro hostname
  await page.waitForTimeout(500);
  await expect(ui(page)).toHaveCount(0);
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page)).toEqual([PROMPT]);           // o site funciona normalmente, sem interferência
  expect(api.requests.filter((r) => r.path.startsWith("/v1/events"))).toHaveLength(0);
});

test("API fora do ar: fail-open envia e avisa; fail-closed bloqueia", async () => {
  let page = await open({ api_url: "http://127.0.0.1:1", fail_mode: "open" });
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  await expect(ui(page).locator(".pill")).toContainText("sem conexão");
  await L!.ctx.close();

  page = await open({ api_url: "http://127.0.0.1:1", fail_mode: "closed" });
  await typeAndSubmit(page, PROMPT);
  await expect(ui(page).locator('[role="dialog"]')).toContainText("Não foi possível verificar");
  expect(await sent(page)).toEqual([]);
});

test("chave errada conta como falha (não como liberação)", async () => {
  const page = await open({ api_key: "ps_errada", fail_mode: "closed" });
  await typeAndSubmit(page, PROMPT);
  await expect(ui(page).locator('[role="dialog"]')).toContainText("Não foi possível verificar");
  expect(await sent(page)).toEqual([]);
});

test("sem configuração: avisa na tela e não envia nada à API", async () => {
  const page = await open({ api_url: "", api_key: "" });
  await expect(ui(page).locator(".pill")).toContainText("sem configuração");
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  expect(api.requests.filter((r) => r.path.startsWith("/v1/events"))).toHaveLength(0);
});

test("site que mudou o HTML: o indicador avisa que o monitoramento pode estar inativo", async () => {
  const page = await open({}, "/no-input.html");
  await expect(ui(page).locator(".pill")).toContainText("campo de prompt não encontrado");
});

test("arquivo anexado: o nome vai junto do prompt, o conteúdo nunca", async () => {
  const page = await open();
  await page.locator("#file").setInputFiles({ name: "folha_pagamento.xlsx", mimeType: "application/vnd.ms-excel", buffer: Buffer.from("CONTEUDO-SECRETO-DO-ARQUIVO") });
  await typeAndSubmit(page, "resuma o arquivo");
  await expect.poll(() => api.events.length).toBe(1);
  const content = api.events[0].body.content;
  expect(content.attachments).toEqual([{ name: "folha_pagamento.xlsx", size: 27, mime: "application/vnd.ms-excel" }]);
  expect(JSON.stringify(api.events[0].body)).not.toContain("CONTEUDO-SECRETO");
  // no envio seguinte a lista começa vazia
  await typeAndSubmit(page, "outro prompt sem arquivo");
  await expect.poll(() => api.events.length).toBe(2);
  expect(api.events[1].body.content.attachments).toBeUndefined();
});

test("inspeção parada pela licença: avisa claramente e NUNCA bloqueia o trabalho, nem em modo fechado", async () => {
  api.stopped = true;
  const page = await open({ fail_mode: "closed" });
  await typeAndSubmit(page, "SIMULADO: texto qualquer");
  await expect(ui(page).locator(".pill")).toContainText("PARADA pela licença");
  await expect.poll(() => sent(page)).toEqual(["SIMULADO: texto qualquer"]);       // o prompt foi enviado ao site mesmo assim
  expect(api.events).toHaveLength(1);                                              // e a extensão tentou inspecionar
});
