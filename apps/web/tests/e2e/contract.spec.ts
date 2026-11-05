import { expect, test } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

test("contrato suspenso: aviso em toda tela, leitura funciona e alteração é recusada com a mensagem", async ({ page }) => {
  await login(page, USERS.suspensa);
  const notice = page.getByTestId("contract-notice");
  await expect(notice).toContainText("Contrato suspenso");
  await expect(notice).toContainText("fatura em atraso");
  await expect(notice).toContainText("continuam guardados");
  await page.goto("/history");
  await expect(notice).toBeVisible();                                        // o aviso acompanha a navegação
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Todos os prompts");   // a leitura continua
  await expectAccessible(page);

  await page.goto("/devices");
  await page.getByLabel("Nome (ex.: piloto TI)").fill("não deve criar");
  await page.getByRole("button", { name: "Criar token" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "contrato suspenso" })).toBeVisible();
});

test("empresa ativa não vê aviso de contrato", async ({ page }) => {
  await login(page, USERS.admin);
  await expect(page.getByTestId("tenant-name")).toBeVisible();
  await expect(page.getByTestId("contract-notice")).toHaveCount(0);
});
