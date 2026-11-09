import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, login, logout, USERS } from "./helpers";

interface Collab { id: string; email: string; role: string; active: boolean; department: string | null }

test("colaboradores: administrador cria com função e departamento, a pessoa entra, edita, desativa e reativa", async ({ page }) => {
  const tag = Date.now().toString(36);
  const email = `colab-${tag}@empresa-exemplo.com.br`;
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Colaboradores");
  await expect(page.getByTestId("roles-help")).toContainText("Analista");
  await expectAccessible(page);

  // a pessoa de teste do próprio administrador aparece como "você" e não pode se remover
  const mine = page.getByTestId("collab-row").filter({ hasText: "você" });
  await expect(mine).toHaveCount(1);
  await expect(mine.getByRole("button", { name: /^Remover/ })).toBeDisabled();

  // criar
  await page.getByLabel("E-mail de login").fill(email);
  await page.getByLabel("Nome (opcional)").fill("Colaborador Sintético");
  await page.getByLabel("Função").selectOption("analista");
  await page.getByLabel("Departamento (opcional)").fill("Segurança");
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Colaborador cadastrado" })).toBeVisible();
  const row = page.getByTestId("collab-row").filter({ hasText: email });
  await expect(row).toContainText("Analista");
  await expect(row).toContainText("Segurança");
  const created = (await apiGet<Collab[]>(page, "v1/users")).data.find((u) => u.email === email)!;
  expect(created.role).toBe("analista");
  await expect(page.getByLabel("E-mail de login")).toHaveValue("");

  // e-mail repetido (só muda a caixa) é recusado com mensagem
  await page.getByLabel("E-mail de login").fill(email.toUpperCase());
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "já cadastrado" })).toBeVisible();

  // editar função e departamento
  await row.getByRole("button", { name: `Editar ${email}` }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Função").selectOption("auditor");
  await dlg.getByLabel("Departamento", { exact: true }).fill("Compliance");
  await dlg.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Colaborador atualizado" })).toBeVisible();
  await expect(row).toContainText("Auditor");
  await expect(row).toContainText("Compliance");

  // a pessoa entra com a função cadastrada (e a lista fica escondida para ela)
  await logout(page);
  await login(page, email);
  await expect(page.getByTestId("who")).toContainText("Auditor");
  await page.goto("/collaborators");
  await expect(page.getByText("Só administradores veem e alteram")).toBeVisible();
  await logout(page);

  // desativar e reativar
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  await page.getByTestId("collab-row").filter({ hasText: email }).getByRole("button", { name: `Desativar ${email}` }).click();
  await expect(page.getByRole("status").filter({ hasText: "Acesso desativado" })).toBeVisible();
  await expect(page.getByTestId("collab-row").filter({ hasText: email })).toContainText("Desativado");
  expect((await apiGet<Collab[]>(page, "v1/users")).data.find((u) => u.email === email)!.active).toBe(false);
  await page.getByTestId("collab-row").filter({ hasText: email }).getByRole("button", { name: `Reativar ${email}` }).click();
  await expect(page.getByTestId("collab-row").filter({ hasText: email })).toContainText("Ativo");

  // remover
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("collab-row").filter({ hasText: email }).getByRole("button", { name: `Remover ${email}` }).click();
  await expect(page.getByRole("status").filter({ hasText: "Colaborador removido" })).toBeVisible();
  await expect(page.getByTestId("collab-row").filter({ hasText: email })).toHaveCount(0);
});

test("colaboradores: o único administrador não se rebaixa nem se desativa", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  const mine = page.getByTestId("collab-row").filter({ hasText: "você" });
  await mine.getByRole("button", { name: /^Desativar/ }).click();
  await expect(page.getByRole("alert").filter({ hasText: /último administrador|a si mesmo/ })).toBeVisible();
  await mine.getByRole("button", { name: /^Editar/ }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Função").selectOption("leitura");
  await dlg.getByRole("button", { name: "Salvar" }).click();
  await expect(dlg.getByRole("alert")).toBeVisible();
});
