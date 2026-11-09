import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, login, logout, USERS } from "./helpers";

const LOCAL = "http://127.0.0.1:3098";      // console com AUTH_MODE=local (e-mail e senha); o outro (3099) é o login simulado
const NEW = "Outra-Senha#77";
const GENERIC = "e-mail ou senha incorretos";

async function localLogin(page: Page, email: string, password: string) {
  await page.goto(`${LOCAL}/login`);
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
}

/** Tentativa que DEVE falhar: espera a resposta (senão a próxima navegação cancela o pedido e o servidor não conta o erro). */
async function localLoginFails(page: Page, email: string, password: string) {
  await localLogin(page, email, password);
  await expect(page.getByRole("alert").filter({ hasText: GENERIC })).toBeVisible();
  await expect(page).toHaveURL(`${LOCAL}/login`);
}

test("login com senha: o administrador cria, a pessoa entra com a senha provisória, é obrigada a trocar e depois usa a nova", async ({ page }) => {
  const email = `senha-${Date.now().toString(36)}@empresa-exemplo.com.br`;

  // 1) administrador (login simulado) cria o colaborador SEM senha: o sistema gera a temporária e mostra uma vez
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  await page.getByLabel("E-mail de login").fill(email);
  await page.getByLabel("Função").first().selectOption("analista");
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  const shown = page.getByTestId("temp-password-value");
  await expect(shown).toBeVisible();
  const temp = (await shown.innerText()).trim();
  expect(temp.length).toBe(14);
  await page.getByRole("button", { name: "Já anotei" }).click();
  await expect(page.getByTestId("collab-row").filter({ hasText: email })).toContainText("senha provisória");
  await logout(page);

  // 2) a tela de login pede e-mail e senha; erro é genérico
  await page.goto(`${LOCAL}/login`);
  await expect(page.getByLabel("Senha", { exact: true })).toBeVisible();
  await expectAccessible(page, "login com senha");
  await localLoginFails(page, email, "Errada#12345");
  await localLoginFails(page, "ninguem@empresa-exemplo.com.br", "Errada#12345");      // a mesma mensagem: não revela quem existe

  // 3) senha provisória: cai na troca obrigatória e nada mais abre
  await localLogin(page, email, temp);
  await expect(page).toHaveURL(`${LOCAL}/change-password`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Defina a sua senha");
  await page.goto(`${LOCAL}/history`);
  await expect(page).toHaveURL(`${LOCAL}/change-password`);                      // tentar entrar no console volta para a troca
  await page.getByLabel("Senha provisória").fill(temp);
  const save = page.getByRole("button", { name: "Salvar nova senha" });
  await page.getByLabel("Nova senha", { exact: true }).fill("123456");
  await expect(save).toBeDisabled();
  await expect(page.getByTestId("password-rules")).toContainText("Uma letra maiúscula");
  await page.getByLabel("Nova senha", { exact: true }).fill(NEW);
  await page.getByLabel("Repita a nova senha").fill("Outra-Senha#78");
  await expect(save).toBeDisabled();                                              // confirmação diferente
  await page.getByLabel("Repita a nova senha").fill(NEW);
  await expectAccessible(page, "troca de senha");
  await save.click();
  await expect(page).toHaveURL(`${LOCAL}/`);
  await expect(page.getByTestId("who")).toContainText(email);
  await expect(page.getByTestId("who")).toContainText("Analista");
  await expect(page.getByRole("link", { name: "Alterar senha" })).toBeVisible();

  // 4) sair e entrar com a nova; a provisória não vale mais
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(`${LOCAL}/login`);
  await localLoginFails(page, email, temp);
  await localLogin(page, email, NEW);
  await expect(page).toHaveURL(`${LOCAL}/`);
  await expect(page.getByTestId("who")).toContainText(email);

  // 5) alterar a própria senha (exige a atual)
  await page.getByRole("link", { name: "Alterar senha" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Alterar senha");
  await page.getByLabel("Senha atual").fill("Errada#12345");
  await page.getByLabel("Nova senha", { exact: true }).fill("Mais-Uma#2026");
  await page.getByLabel("Repita a nova senha").fill("Mais-Uma#2026");
  await page.getByRole("button", { name: "Salvar nova senha" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "senha atual está incorreta" })).toBeVisible();
});

test("login com senha: erros seguidos bloqueiam, e o administrador desbloqueia gerando uma senha temporária nova", async ({ page }) => {
  const email = `bloq-${Date.now().toString(36)}@empresa-exemplo.com.br`;
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  await page.getByLabel("E-mail de login").fill(email);
  await page.getByLabel("Senha inicial (opcional", { exact: false }).fill("Teste-PS-2026!");
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Colaborador cadastrado" })).toBeVisible();
  await logout(page);

  for (let i = 0; i < 5; i++) await localLoginFails(page, email, `Errada#${i}abcdef`);
  await localLoginFails(page, email, "Teste-PS-2026!");                           // senha CERTA, mas bloqueado

  await page.goto("/login");
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  const row = page.getByTestId("collab-row").filter({ hasText: email });
  await expect(row).toContainText("bloqueado por tentativas");
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: `Nova senha temporária para ${email}` }).click();
  const temp = (await page.getByTestId("temp-password-value").innerText()).trim();
  await page.getByRole("button", { name: "Já anotei" }).click();
  await expect(row).not.toContainText("bloqueado por tentativas");
  await localLogin(page, email, temp);
  await expect(page).toHaveURL(`${LOCAL}/change-password`);
});

test("login com senha: o administrador não gera senha temporária para si mesmo; a política vale na senha inicial", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/collaborators");
  await expect(page.getByTestId("collab-row").filter({ hasText: "você" }).getByRole("button", { name: /Nova senha temporária/ })).toHaveCount(0);
  await page.getByLabel("E-mail de login").fill(`fraca-${Date.now().toString(36)}@empresa-exemplo.com.br`);
  await page.getByLabel("Senha inicial (opcional", { exact: false }).fill("123456");
  await expect(page.getByText("Uma letra maiúscula").first()).toBeVisible();
  await page.getByRole("button", { name: "Adicionar", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "não cumpre a política" })).toBeVisible();
});

test("login com senha: cada função (analista, auditor, leitura) troca a própria senha e não vê Colaboradores", async ({ page }) => {
  const tag = Date.now().toString(36);
  const roles = [["analista", "Analista"], ["auditor", "Auditor"], ["leitura", "Leitura"]] as const;
  await login(page, USERS.admin);
  for (const [role] of roles) {       // o administrador cadastra cada um com uma senha inicial (a API recusa criar sem ser admin)
    const status = await page.evaluate(async (b) => (await fetch("/api/proxy/v1/users", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "promptshield" }, body: JSON.stringify(b) })).status,
      { email: `${role}-${tag}@empresa-exemplo.com.br`, role, password: "Inicial-PS-2026!" });
    expect(status).toBe(201);
  }
  await logout(page);

  for (const [role, label] of roles) {
    const email = `${role}-${tag}@empresa-exemplo.com.br`;
    await localLogin(page, email, "Inicial-PS-2026!");
    await expect(page).toHaveURL(`${LOCAL}/change-password`);                      // troca obrigatória, para qualquer função
    await page.getByLabel("Senha provisória").fill("Inicial-PS-2026!");
    await page.getByLabel("Nova senha", { exact: true }).fill(NEW);
    await page.getByLabel("Repita a nova senha").fill(NEW);
    await page.getByRole("button", { name: "Salvar nova senha" }).click();
    await expect(page).toHaveURL(`${LOCAL}/`);
    await expect(page.getByTestId("who")).toContainText(label);
    await expect(page.getByRole("link", { name: "Alterar senha" })).toBeVisible();   // o lugar para trocar a própria senha, sempre no topo
    await expect(page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Colaboradores" })).toHaveCount(0);
    // trocar de novo, já logado, pelo botão do topo
    await page.getByRole("link", { name: "Alterar senha" }).click();
    await page.getByLabel("Senha atual").fill(NEW);
    await page.getByLabel("Nova senha", { exact: true }).fill("Terceira-Senha#9");
    await page.getByLabel("Repita a nova senha").fill("Terceira-Senha#9");
    await page.getByRole("button", { name: "Salvar nova senha" }).click();
    await expect(page).toHaveURL(`${LOCAL}/`);
    await page.getByRole("button", { name: "Sair" }).click();
    await expect(page).toHaveURL(`${LOCAL}/login`);
    await localLogin(page, email, "Terceira-Senha#9");
    await expect(page.getByTestId("who")).toContainText(label);
    await page.getByRole("button", { name: "Sair" }).click();
    await expect(page).toHaveURL(`${LOCAL}/login`);
  }
});
