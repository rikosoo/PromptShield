import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, login, logout, USERS } from "./helpers";

interface Summary { coverage: { active_users: number; expected_users: number | null; rate: number | null }; false_positive: { reviewed: number; pending: number; false_positive: number; decided: number; rate: number | null; small_sample: boolean }; monitor_only: boolean; time_to_first_alert_seconds: number | null }
interface DataMap { counts: { events: number; distinct_monitored_people: number; events_with_original: number }; retention_days: number }

test("piloto: configurar, sortear amostra, revisar e ver os números da API na tela", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/pilot");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Piloto de 30 dias");
  await page.getByLabel("Usuários esperados").fill("15");
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Configuração do piloto salva." })).toBeVisible();

  let s = (await apiGet<Summary>(page, "v1/pilot/summary")).data;
  expect(s.coverage.expected_users).toBe(15);
  expect(s.coverage.active_users).toBeGreaterThan(5);                                  // os usuários dos dados de exemplo
  const kpi = (label: string) => page.getByTestId("kpi").filter({ hasText: label }).locator("div").first();
  await expect(kpi("Cobertura de usuários")).toHaveText(`${((s.coverage.rate ?? 0) * 100).toFixed(1)}%`);
  await expect(page.getByTestId("monitor-only")).toContainText(s.monitor_only ? "Modo só monitorar confirmado" : "ATENÇÃO");

  await page.getByLabel("Tamanho da amostra").fill("6");
  await page.getByRole("button", { name: "Sortear amostra" }).click();
  await expect(page.getByTestId("review-item")).toHaveCount(6);
  await expect(page.getByTestId("review-item").first()).not.toContainText("@@");        // texto sempre mascarado
  const labels = ["Falso positivo", "Verdadeiro positivo", "Verdadeiro positivo", "Verdadeiro positivo", "Incerto", "Verdadeiro positivo"];
  for (const l of labels) {
    const before = await page.getByTestId("review-item").count();
    await page.getByTestId("review-item").first().getByRole("button", { name: l, exact: true }).click();
    await expect(page.getByTestId("review-item")).toHaveCount(before - 1);
  }
  s = (await apiGet<Summary>(page, "v1/pilot/summary")).data;
  expect(s.false_positive).toMatchObject({ reviewed: 6, pending: 0, false_positive: 1, decided: 5 });
  expect(s.false_positive.rate).toBe(0.2);
  expect(s.false_positive.small_sample).toBe(true);
  await expect(kpi("Falso positivo (revisado)")).toHaveText("20.0%");
  await expect(page.getByTestId("small-sample")).toContainText("Amostra pequena");

  await page.getByRole("button", { name: "Gerar relatório final (PDF)" }).click();
  const link = page.getByRole("link", { name: "Baixar PDF" });
  await expect(link).toBeVisible();
  const pdf = await page.request.get((await link.getAttribute("href"))!);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  await logout(page);
  await login(page, USERS.auditor);
  await page.goto("/pilot");
  await expect(page.getByText("Só administrador e analista revisam.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sortear amostra" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Iniciar piloto agora" })).toHaveCount(0);
});

test("privacidade: mapa de dados, retenção, direito do titular e chaves de API", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/privacy");
  const map = (await apiGet<DataMap>(page, "v1/privacy/data-map")).data;
  const kpi = (label: string) => page.getByTestId("kpi").filter({ hasText: label }).locator("div").first();
  await expect(kpi("Eventos guardados")).toHaveText(String(map.counts.events));
  await expect(kpi("Pessoas monitoradas")).toHaveText(String(map.counts.distinct_monitored_people));
  await expect(kpi("Retenção")).toHaveText(`${map.retention_days} dias`);

  await page.getByLabel("Guardar eventos por (dias)").fill("120");
  await page.getByLabel("Guardar texto original por (dias)").fill("10");
  await page.getByRole("button", { name: "Salvar prazos" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Retenção salva." })).toBeVisible();
  const t = (await apiGet<{ retention_days: number; original_retention_days: number }>(page, "v1/tenant")).data;
  expect([t.retention_days, t.original_retention_days]).toEqual([120, 10]);
  const field = page.getByLabel("Guardar eventos por (dias)");
  await field.fill("3");                                                                 // fora do limite (mínimo 7): o navegador não deixa enviar
  expect(await field.evaluate((el) => (el as HTMLInputElement).checkValidity())).toBe(false);
  await page.getByRole("button", { name: "Salvar prazos" }).click();
  expect((await apiGet<{ retention_days: number }>(page, "v1/tenant")).data.retention_days).toBe(120);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Executar retenção agora" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Retenção executada" })).toBeVisible();
  expect((await apiGet<DataMap>(page, "v1/privacy/data-map")).data.counts.events).toBe(map.counts.events);   // 14 dias de dados: nada venceu

  // texto livre sensível: saúde vem marcada; desmarcar e marcar de novo muda o que o tenant guarda
  const omit = page.getByTestId("omit-categories");
  await omit.locator("summary").click();
  await expect(omit.getByLabel("Dados de saúde")).toBeChecked();
  await omit.getByLabel("Dados de saúde").click();        // controlado: só muda depois que a API responde
  await expect(page.getByRole("status").filter({ hasText: "Categorias sem guarda de texto atualizadas." })).toBeVisible();
  expect((await apiGet<{ omit_text_categories: string[] }>(page, "v1/tenant")).data.omit_text_categories).toEqual([]);
  await omit.getByLabel("Dados de saúde").click();
  await expect.poll(async () => (await apiGet<{ omit_text_categories: string[] }>(page, "v1/tenant")).data.omit_text_categories).toEqual(["saude"]);

  // titular: consulta e eliminação de UMA pessoa dos dados de exemplo
  const evs = (await apiGet<{ user_id: string }[]>(page, "v1/events?limit=200&days=14")).data;
  const person = evs[0].user_id;
  const exported = (await apiGet<{ events: unknown[] }>(page, `v1/privacy/subject?user_id=${encodeURIComponent(person)}`)).data;
  await page.getByLabel(/^Identificador da pessoa/).fill(person);
  await page.getByRole("button", { name: "Consultar o que guardamos" }).click();
  await expect(page.getByTestId("subject-events")).toHaveText(String(exported.events.length));
  const erase = page.getByRole("button", { name: "Eliminar os dados desta pessoa" });
  await expect(erase).toBeDisabled();                                                    // exige justificativa
  await page.getByLabel(/^Justificativa da eliminação/).fill("pedido do titular, protocolo e2e 1");
  await expect(erase).toBeEnabled();
  page.once("dialog", (d) => d.accept());
  await erase.click();
  await expect(page.getByRole("status").filter({ hasText: "Eliminado:" })).toBeVisible();
  expect((await apiGet<{ events: unknown[] }>(page, `v1/privacy/subject?user_id=${encodeURIComponent(person)}`)).data.events).toHaveLength(0);
  expect((await apiGet<DataMap>(page, "v1/privacy/data-map")).data.counts.events).toBe(map.counts.events - exported.events.length);

  // chaves: criar, rotacionar (a antiga continua valendo por um tempo) e revogar
  await page.getByLabel("Nova chave (nome)").fill("chave de teste e2e");
  await page.getByRole("button", { name: "Criar chave" }).click();
  await expect(page.getByTestId("new-key")).toHaveText(/^ps_[0-9a-f]{8}_/);
  await page.getByRole("button", { name: "Já guardei" }).click();
  const row = page.getByTestId("key-row").filter({ hasText: "chave de teste e2e" });
  await expect(row).toContainText("ativa");
  await row.getByRole("button", { name: "Rotacionar" }).click();
  await expect(page.getByTestId("new-key")).toHaveText(/^ps_[0-9a-f]{8}_/);
  await page.getByRole("button", { name: "Já guardei" }).click();
  await expect(page.getByTestId("key-row").filter({ hasText: "chave de teste e2e" }).filter({ hasText: "expira em breve" })).toHaveCount(1);
  // relativo ao que já havia: outros testes (dispositivos, sensores) também revogam chaves no mesmo tenant, então a contagem global não é fixa
  const revokedBefore = await page.getByTestId("key-row").filter({ hasText: "revogada" }).count();
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("key-row").filter({ hasText: "chave de teste e2e" }).filter({ hasText: "ativa" }).getByRole("button", { name: "Revogar" }).click();
  await expect(page.getByTestId("key-row").filter({ hasText: "revogada" })).toHaveCount(revokedBefore + 1);

  await logout(page);
  await login(page, USERS.analista);
  await page.goto("/privacy");
  await expect(page.getByText("Só o administrador altera a retenção.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Criar chave" })).toHaveCount(0);
  await expect(page.getByText("Só administrador e auditor consultam; só o administrador elimina.")).toBeVisible();
});

test("piloto e privacidade: acessibilidade, tema escuro e tablet", async ({ page }) => {
  await login(page, USERS.admin);
  for (const path of ["/pilot", "/privacy"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessible(page, path);
  }
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await expectAccessible(page, "tema escuro em /privacy");
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await page.setViewportSize({ width: 768, height: 1024 });
  for (const path of ["/pilot", "/privacy"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), path).toBeLessThanOrEqual(0);
  }
});
