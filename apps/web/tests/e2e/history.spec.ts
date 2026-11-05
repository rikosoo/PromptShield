import { expect, test } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

test("todos os prompts: filtrar por pessoa e palavra-chave, abrir detalhe, exportar só admin/auditor", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/history");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Todos os prompts");
  await expectAccessible(page);

  const rows = page.getByTestId("history-row");
  await expect(rows.first()).toBeVisible();
  const total = Number((await page.getByTestId("history-total").innerText()).split(" ")[0]);
  expect(total).toBeGreaterThan(0);

  // pessoa: clicar na lista de pessoas filtra e mostra só ela
  const person = page.getByTestId("people").getByRole("button").first();
  const who = (await person.locator("span.font-medium").innerText()).trim();
  await person.click();
  await expect(person).toHaveAttribute("aria-pressed", "true");
  await expect(rows.first()).toBeVisible();
  await expect.poll(async () => (await rows.locator("td:nth-child(2) button").allInnerTexts()).every((t) => t.trim() === who)).toBe(true);

  // palavra sem resultado
  await page.getByLabel("Palavra-chave (prompt ou arquivo)").fill("zzzz-nao-existe");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await expect(page.getByText("Nenhum prompt com esses filtros.")).toBeVisible();
  await page.getByRole("button", { name: "Limpar filtros" }).click();
  await expect(rows.first()).toBeVisible();

  // detalhe
  await rows.first().getByRole("button", { name: /Ver detalhes/ }).click();
  await expect(page.getByTestId("prompt-detail")).toBeVisible();
  await page.getByRole("button", { name: "Fechar" }).first().click();

  // exportação: só admin/auditor
  await expect(page.getByTestId("export-csv")).toBeVisible();
  const csv = await page.request.get((await page.getByTestId("export-csv").getAttribute("href"))!);
  expect(csv.status()).toBe(200);
  expect(await csv.text()).toContain("quando_utc,pessoa");
});

test("todos os prompts: leitura vê a lista mas não o botão de exportar", async ({ page }) => {
  await login(page, USERS.leitura);
  await page.goto("/history");
  await expect(page.getByTestId("history-row").first()).toBeVisible();
  await expect(page.getByTestId("export-csv")).toHaveCount(0);
});

test("todos os prompts: filtrar só os que têm arquivo anexado e ver o nome do arquivo", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/history");
  await page.getByLabel("Só com arquivo anexado").check();
  const rows = page.getByTestId("history-row");
  await expect.poll(async () => (await rows.count()) > 0 && (await rows.getByTestId("attachments").count()) === (await rows.count())).toBe(true);
  await expect(rows.first().getByTestId("attachments")).toContainText("📎");
  await rows.first().getByRole("button", { name: /Ver detalhes/ }).click();
  await expect(page.getByTestId("prompt-detail").getByText("Arquivos anexados")).toBeVisible();
  await expectAccessible(page);
});
