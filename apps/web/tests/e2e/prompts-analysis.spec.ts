import { expect, test } from "@playwright/test";
import { expectAccessible, login, openPanel, USERS } from "./helpers";

test("análise de prompts: sinais clicáveis, busca no texto mascarado, detalhe com trechos e atualização automática", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/prompts");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Análise de prompts");
  await openPanel(page, "panel-sinais");
  const signals = page.getByTestId("signals");
  await expect(signals).toBeVisible();
  await expect(signals.getByText("Segredos e dados detectados")).toBeVisible();
  await expectAccessible(page);

  // clicar num tipo de trecho filtra a lista e mostra os trechos no detalhe
  const chip = signals.getByRole("button", { pressed: false }).first();
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(signals.getByRole("button", { pressed: true }).first()).toBeVisible();
  const rows = page.getByTestId("prompt-row");
  await expect(rows.first()).toBeVisible();
  await rows.first().getByRole("button").first().click();
  await expect(page.getByTestId("prompt-detail")).toBeVisible();
  await page.getByRole("button", { name: "Fechar" }).first().click();

  // limpar e buscar no texto mascarado (nunca no original)
  await openPanel(page, "panel-filtros");
  await page.getByRole("button", { name: "Limpar filtros de sinais" }).click();
  await page.getByLabel("Buscar no texto mascarado").fill("zzzz-nao-existe");
  await page.getByRole("button", { name: "Buscar" }).click();
  await expect(page.getByText("Nenhum prompt com esses filtros.")).toBeVisible();
  await page.getByRole("button", { name: "Limpar filtros de sinais" }).click();
  await expect(rows.first()).toBeVisible();

  // atualização automática liga e desliga
  const live = page.getByLabel("Atualizar sozinho a cada 10 s");
  await live.check();
  await expect(live).toBeChecked();
  await live.uncheck();
});

test("análise de prompts: os blocos de filtro começam recolhidos, com resumo de uma linha, e abrem ao clicar", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/prompts");
  for (const id of ["panel-categorias", "panel-sinais", "panel-filtros"]) {
    const box = page.getByTestId(id);
    const btn = box.getByRole("button").first();
    await expect(btn).toHaveAttribute("aria-expanded", "false");
    expect((await box.boundingBox())!.height).toBeLessThan(60);                    // uma linha só
    await expect(btn).toContainText(/\S\s+\S|\S{4,}/);                              // tem resumo ao lado do título
  }
  await expect(page.getByTestId("signals")).toBeHidden();
  await expect(page.getByLabel("Contém código")).toBeHidden();
  await expect(page.getByTestId("panel-filtros").getByRole("button").first()).toContainText("só com risco");   // o filtro padrão aparece no resumo

  await openPanel(page, "panel-filtros");
  await expect(page.getByLabel("Contém código")).toBeVisible();
  await page.getByLabel("Contém código").check();
  await page.getByTestId("panel-filtros").getByRole("button").first().click();     // fecha de novo
  await expect(page.getByLabel("Contém código")).toBeHidden();
  await expect(page.getByTestId("panel-filtros").getByRole("button").first()).toContainText("contém código");   // o resumo acompanha o filtro ativo
  await expectAccessible(page, "blocos recolhidos");
  await openPanel(page, "panel-categorias");
  await openPanel(page, "panel-sinais");
  await openPanel(page, "panel-filtros");
  await expectAccessible(page, "blocos abertos");
});
