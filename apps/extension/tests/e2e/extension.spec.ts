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

for (const mode of ["mask", "block", "ask_justification", "alert"] as const) {
  test(`PASSIVO: mesmo que a API devolva "${mode}", o envio segue na hora, com o texto ORIGINAL, sem diálogo nem bloqueio`, async () => {
    api.mode = mode;
    const page = await open();
    await typeAndSubmit(page, PROMPT);
    await expect.poll(() => sent(page), { timeout: 1500 }).toEqual([PROMPT]);        // o site recebeu o prompt intacto (nada mascarado, nada retido)
    await expect(ui(page).locator('[role="dialog"]')).toHaveCount(0);                 // nenhuma janela, nenhuma pergunta ao usuário
    await expect.poll(() => api.events.length).toBe(1);                              // e ainda assim o evento foi registrado, em segundo plano
    expect(api.events[0].body).toMatchObject({ kind: "prompt", source: { channel: "browser", app: "chatgpt_web", integration_status: "partial" },
      actor: { user_id: "rafael.moreira", department: "Engenharia" }, content: { text: PROMPT }, context: { personal_account: false } });
    expect(JSON.stringify(await sent(page))).toContain(CPF);                         // o PromptShield NÃO altera o prompt enviado à ferramenta de IA
  });
}

test("PASSIVO: API lenta não atrasa o envio do usuário", async () => {
  api.mode = "allow";
  api.delayMs = 3000;
  const page = await open();
  const t0 = Date.now();
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page), { timeout: 1000 }).toEqual([PROMPT]);
  expect(Date.now() - t0).toBeLessThan(1500);                                        // o envio não esperou os 3 s da análise
  expect(api.events).toHaveLength(0);                                                // a análise ainda está em andamento em segundo plano
  await expect.poll(() => api.events.length, { timeout: 6000 }).toBe(1);
});

test("PASSIVO: os eventos de teclado e de clique do envio continuam chegando ao site (a extensão não para a propagação)", async () => {
  const page = await open();
  await page.evaluate(() => {
    const w = window as any;
    w.__seen = [];
    for (const type of ["keydown", "click"]) document.addEventListener(type, () => w.__seen.push(type), false);   // ouvinte em bolha: não roda se alguém parar a propagação
  });
  await typeAndSubmit(page, "sem dados sensíveis", "enter");
  await typeAndSubmit(page, "outro", "click");
  await expect.poll(() => sent(page)).toEqual(["sem dados sensíveis", "outro"]);
  const seen = await page.evaluate(() => (window as any).__seen as string[]);
  expect(seen.filter((x) => x === "keydown").length).toBeGreaterThanOrEqual(1);
  expect(seen.filter((x) => x === "click").length).toBeGreaterThanOrEqual(1);
});

test("política em monitorar (allow): envia o original sem diálogo, por Enter e por clique", async () => {
  api.mode = "allow";
  const page = await open();
  await typeAndSubmit(page, PROMPT, "enter");
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  await typeAndSubmit(page, "outro prompt sem dados", "click");
  await expect.poll(() => sent(page)).toEqual([PROMPT, "outro prompt sem dados"]);
  await expect(ui(page).locator('[role="dialog"]')).toHaveCount(0);
  await expect.poll(() => api.events.length).toBe(2);      // o registro é em segundo plano
});

test("campo textarea: o prompt original segue e é registrado", async () => {
  api.mode = "mask";
  const page = await open({}, "/chat-textarea.html");
  await page.locator("#prompt").fill(PROMPT);
  await page.keyboard.press("Enter");
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  await expect.poll(() => api.events.length).toBe(1);
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
  api.mode = "allow";
  L = await launchWithExtension(config());                         // domains = ["127.0.0.1"]
  const page = await L.ctx.newPage();
  await page.goto(`http://localhost:${api.port}/chat.html`);        // mesmo servidor, outro hostname
  await page.waitForTimeout(500);
  await expect(ui(page)).toHaveCount(0);
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page)).toEqual([PROMPT]);           // o site funciona normalmente, sem interferência
  expect(api.requests.filter((r) => r.path.startsWith("/v1/events"))).toHaveLength(0);
});

test("API fora do ar: o envio segue e o indicador avisa que não foi registrado, mesmo com fail_mode closed", async () => {
  for (const failMode of ["open", "closed"]) {
    const page = await open({ api_url: "http://127.0.0.1:1", fail_mode: failMode });
    await typeAndSubmit(page, PROMPT);
    await expect.poll(() => sent(page)).toEqual([PROMPT]);                          // PASSIVO: nunca impede o envio por falha do analisador
    await expect(ui(page).locator(".pill")).toContainText("sem conexão");
    await expect(ui(page).locator('[role="dialog"]')).toHaveCount(0);
    await L!.ctx.close();
    L = undefined;
  }
});

test("chave errada: o envio segue e o indicador avisa", async () => {
  const page = await open({ api_key: "ps_errada", fail_mode: "closed" });
  await typeAndSubmit(page, PROMPT);
  await expect.poll(() => sent(page)).toEqual([PROMPT]);
  await expect(ui(page).locator(".pill")).toContainText("não foi registrado");
  await expect(ui(page).locator('[role="dialog"]')).toHaveCount(0);
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

test("inspeção parada pela licença: avisa claramente e o trabalho segue, nem em modo fechado", async () => {
  api.stopped = true;
  const page = await open({ fail_mode: "closed" });
  await typeAndSubmit(page, "SIMULADO: texto qualquer");
  await expect(ui(page).locator(".pill")).toContainText("PARADA pela licença");
  await expect.poll(() => sent(page)).toEqual(["SIMULADO: texto qualquer"]);       // o prompt foi enviado ao site mesmo assim
  expect(api.events).toHaveLength(1);                                              // e a extensão tentou inspecionar
});
