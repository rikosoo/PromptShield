import { expect, test } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

test("revisão humana: marcar análise como correta, ver o selo na lista e o resumo em Qualidade da detecção", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/history");
  await page.getByLabel("Só com risco").check();
  const rows = page.getByTestId("history-row");
  await expect(rows.first()).toBeVisible();
  await rows.first().getByRole("button", { name: /Ver detalhes/ }).click();
  const form = page.getByTestId("feedback-form");
  await expect(form).toBeVisible();
  await expectAccessible(page);
  await expect(form.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
  await form.getByRole("button", { name: "Análise correta" }).click();
  await form.getByRole("button", { name: "Salvar revisão" }).click();
  await expect(page.getByTestId("feedback-saved")).toContainText("Análise correta");
  await page.getByRole("button", { name: "Fechar" }).first().click();
  await page.getByLabel("Revisão humana").selectOption("correta");
  await expect(rows.first().getByTestId("reviewed-badge")).toContainText("Análise correta");

  await page.goto("/quality");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Qualidade da detecção");
  await expect(page.getByTestId("quality-summary")).toBeVisible();
  await expect(page.getByTestId("quality-row").first()).toBeVisible();
  await expect(page.getByTestId("export-feedback")).toHaveCount(0);      // analista não exporta
  await expectAccessible(page);
});

test("revisão humana: falso positivo exige a categoria; leitura vê só o resultado; auditor exporta", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/history");
  await page.getByLabel("Só com risco").check();
  const rows = page.getByTestId("history-row");
  await expect(rows.first()).toBeVisible();
  await rows.first().getByRole("button", { name: /Ver detalhes/ }).click();
  const form = page.getByTestId("feedback-form");
  await form.getByRole("button", { name: "Falso positivo" }).click();
  await expect(form.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();           // falta marcar a categoria errada
  await form.getByRole("group", { name: "Categorias erradas" }).getByRole("button").first().click();
  await form.getByRole("button", { name: "Salvar revisão" }).click();
  await expect(page.getByTestId("feedback-saved")).toContainText("Falso positivo");

  await page.context().clearCookies();
  await login(page, USERS.leitura);
  await page.goto("/history");
  await page.getByLabel("Revisão humana").selectOption("falso_positivo");
  const r = page.getByTestId("history-row").first();
  await expect(r).toBeVisible();
  await r.getByRole("button", { name: /Ver detalhes/ }).click();
  await expect(page.getByTestId("feedback-readonly")).toContainText("Falso positivo");
  await expect(page.getByTestId("feedback-form")).toHaveCount(0);

  await page.context().clearCookies();
  await login(page, USERS.auditor);
  await page.goto("/quality");
  const href = await page.getByTestId("export-feedback").getAttribute("href");
  const res = await page.request.get(href!);
  expect(res.status()).toBe(200);
  expect(await res.text()).toContain("revisao_humana");
});
