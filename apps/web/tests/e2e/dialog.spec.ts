import { expect, test } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

test("janelas: fecham pelo X, clicando fora e com Esc; clicar dentro ou arrastar para fora não fecham", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/prompts");
  const row = page.getByTestId("prompt-row").first();
  await expect(row).toBeVisible();
  const dlg = page.getByTestId("prompt-detail");
  const open = async () => { await row.getByRole("button").first().click(); await expect(dlg).toBeVisible(); };

  await open();
  await expect(page.getByRole("button", { name: "Fechar" }).first()).toBeVisible();      // o X existe
  await expectAccessible(page, "janela com o botão X");
  await page.getByRole("heading", { name: "Detalhe do prompt" }).click();                // clicar dentro NÃO fecha
  await expect(dlg).toBeVisible();

  const box = (await dlg.boundingBox())!;                                                // arrastar de dentro para fora NÃO fecha (selecionar texto)
  await page.mouse.move(box.x + 30, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(3, 3);
  await page.mouse.up();
  await expect(dlg).toBeVisible();

  await page.getByRole("button", { name: "Fechar" }).first().click();                   // X
  await expect(dlg).toBeHidden();

  await open();
  await page.mouse.click(3, 3);                                                          // clicar fora (no fundo escuro)
  await expect(dlg).toBeHidden();

  await open();
  await page.keyboard.press("Escape");                                                   // Esc continua funcionando
  await expect(dlg).toBeHidden();
});

test("janela do token: avisa antes de fechar (o token só aparece uma vez), por X, clique fora e Esc", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/devices");
  await page.getByLabel("Nome (ex.: piloto TI)").fill("teste-janela");
  await page.getByRole("button", { name: "Criar token" }).click();
  const token = page.getByTestId("new-token");
  await expect(token).toBeVisible();

  const messages: string[] = [];
  const answer = (accept: boolean) => page.once("dialog", async (d) => { messages.push(d.message()); await (accept ? d.accept() : d.dismiss()); });

  for (const how of ["x", "fora", "esc"] as const) {
    answer(false);                                                                       // "não, ainda não copiei": a janela fica aberta
    if (how === "x") await page.getByRole("button", { name: "Fechar" }).first().click();
    else if (how === "fora") await page.mouse.click(3, 3);
    else await page.keyboard.press("Escape");
    await expect.poll(() => messages.length).toBeGreaterThan(["x", "fora", "esc"].indexOf(how));
    await expect(token).toBeVisible();
  }
  expect(messages.every((m) => m.includes("só desta vez"))).toBe(true);

  answer(true);                                                                          // "sim, já copiei": fecha
  await page.mouse.click(3, 3);
  await expect(token).toBeHidden();
});
