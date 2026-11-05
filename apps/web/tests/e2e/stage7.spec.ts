import { createServer } from "node:http";
import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, formAlert, login, logout, USERS } from "./helpers";

interface Risk { score_version: string; users: { user_id: string; score: number }[]; departments: { department: string; score: number }[] }
interface Overview { totals: { events: number; high_risk: number; users: number; blocked: number } }
interface AlertRow { id: string; count: number }

const utcDay = (offset = 0) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

test("risco por usuário: aviso de revisão humana e números iguais aos da API", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/risk");
  await expect(page.getByTestId("risk-disclaimer")).toContainText("requer revisão humana");
  const r = (await apiGet<Risk>(page, "v1/stats/risk?days=14")).data;
  expect(r.users.length).toBeGreaterThan(3);
  await expect(page.getByTestId("user-risk").locator("tbody tr")).toHaveCount(r.users.length);
  await expect(page.getByTestId("dept-risk").locator("tbody tr")).toHaveCount(r.departments.length);
  const first = page.getByTestId("user-risk").locator("tbody tr").first();
  await expect(first).toContainText(r.users[0].user_id);
  await expect(first).toContainText(String(r.users[0].score));
  expect(r.users[0].score).toBeGreaterThanOrEqual(r.users[r.users.length - 1].score);
  await expect(page.getByRole("img", { name: /Evolução do indicador de/ }).first()).toBeVisible();
  await page.getByLabel("Período").selectOption("7");
  const r7 = (await apiGet<Risk>(page, "v1/stats/risk?days=7")).data;
  await expect(page.getByTestId("user-risk").locator("tbody tr")).toHaveCount(r7.users.length);
});

test("alertas: lista da API, canal inválido recusado, teste de webhook assinado e papel sem acesso", async ({ page }) => {
  const received: { headers: Record<string, unknown>; body: string }[] = [];
  const sink = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => { received.push({ headers: req.headers, body }); res.writeHead(200).end(); });
  });
  await new Promise<void>((ok) => sink.listen(0, "127.0.0.1", ok));
  const port = (sink.address() as { port: number }).port;
  try {
    await login(page, USERS.admin);
    await page.goto("/alerts");
    const alerts = (await apiGet<AlertRow[]>(page, "v1/alerts")).data;
    expect(alerts.length).toBeGreaterThan(0);
    await expect(page.getByTestId("alert-row")).toHaveCount(Math.min(alerts.length, 100));
    await page.getByLabel("Regra").selectOption("injection");
    const inj = (await apiGet<AlertRow[]>(page, "v1/alerts?rule=injection")).data;
    await expect(page.getByTestId("alert-row")).toHaveCount(inj.length);
    if (inj.length === 0) await expect(page.getByText("Nenhum alerta no período.")).toBeVisible();

    await page.getByRole("button", { name: "Novo canal" }).click();
    await page.getByLabel("Nome").fill("coletor local");
    await page.getByLabel(/^Destino/).fill("ftp://exemplo.invalid/x");
    await page.getByRole("button", { name: "Criar canal" }).click();
    await expect(formAlert(page)).toContainText("use uma URL https");

    await page.getByLabel(/^Destino/).fill(`http://127.0.0.1:${port}/alerta`);
    await page.getByLabel(/^Segredo para assinatura/).fill("segredo-de-teste-1234");
    await page.getByRole("button", { name: "Criar canal" }).click();
    const row = page.getByTestId("channel-row").filter({ hasText: "coletor local" });
    await expect(row).toContainText("REAL");
    await expect(row).toContainText("assinado");
    await expect(row).not.toContainText("/alerta");                             // o caminho da URL (segredo) não aparece
    await row.getByRole("button", { name: "Testar" }).click();
    await expect(row.getByRole("status")).toHaveText("Teste enviado com sucesso.");
    expect(received).toHaveLength(1);
    expect(received[0].headers["x-promptshield-signature"]).toMatch(/^sha256=[0-9a-f]{64}$/);
    expect(JSON.parse(received[0].body).alert.rule).toBe("teste");

    await row.getByRole("button", { name: "Desligar" }).click();
    await expect(row).toContainText("(desligado)");
    page.once("dialog", (d) => d.accept());
    await row.getByRole("button", { name: "Remover" }).click();
    await expect(page.getByTestId("channel-row")).toHaveCount(0);

    await logout(page);
    await login(page, USERS.analista);
    await page.goto("/alerts");
    await expect(page.getByText("Só o administrador configura canais.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Novo canal" })).toHaveCount(0);
  } finally {
    sink.close();
  }
});

test("relatórios: CSV e PDF baixados trazem os mesmos números do painel", async ({ page }) => {
  await login(page, USERS.auditor);
  await page.goto("/reports");
  await page.getByLabel("De").fill(utcDay(-13));
  await page.getByLabel("Até").fill(utcDay(0));
  await page.getByLabel("Relatório", { exact: true }).first().selectOption("executivo");
  await page.getByLabel("Formato").first().selectOption("csv");
  await page.getByRole("button", { name: "Gerar" }).click();
  const csvRow = page.getByTestId("report-row").filter({ hasText: "Executivo (CSV)" }).first();
  await expect(csvRow).toBeVisible();
  const o = (await apiGet<Overview>(page, "v1/stats/overview?days=14")).data;
  const href = await csvRow.getByRole("link", { name: /Baixar CSV/ }).getAttribute("href");
  const csv = (await (await page.request.get(href!)).text()).replace(/^﻿/, "");
  expect(csv).toContain(`totais,events,${o.totals.events}`);
  expect(csv).toContain(`totais,high_risk,${o.totals.high_risk}`);
  expect(csv).toContain("dados_de_exemplo,sim");
  expect(csv).toContain("requer revisao humana");

  await page.getByLabel("Formato").first().selectOption("pdf");
  await page.getByRole("button", { name: "Gerar" }).click();
  const pdfRow = page.getByTestId("report-row").filter({ hasText: "Executivo (PDF)" }).first();
  await expect(pdfRow).toBeVisible();
  const pdf = await page.request.get((await pdfRow.getByRole("link", { name: /Baixar PDF/ }).getAttribute("href"))!);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  await expect(page.getByRole("button", { name: "Agendar" })).toHaveCount(0);   // auditor não agenda
  await logout(page);
  await login(page, USERS.admin);
  await page.goto("/reports");
  await page.getByLabel("E-mails (separe por vírgula; opcional)").fill("sem-arroba");
  await page.getByRole("button", { name: "Agendar" }).click();
  await expect(formAlert(page)).toContainText("e-mail inválido");
  await page.getByLabel("E-mails (separe por vírgula; opcional)").fill("");
  await page.getByRole("button", { name: "Agendar" }).click();
  await expect(page.getByTestId("schedules")).toContainText("mensal");
});

test("novas telas: acessibilidade, tema escuro e tablet", async ({ page }) => {
  await login(page, USERS.admin);
  for (const path of ["/risk", "/alerts", "/reports", "/inference-hooks"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessible(page, path);
  }
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await expectAccessible(page, "tema escuro em /reports");
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await page.setViewportSize({ width: 768, height: 1024 });
  for (const path of ["/risk", "/alerts", "/reports", "/inference-hooks"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), path).toBeLessThanOrEqual(0);
  }
});
