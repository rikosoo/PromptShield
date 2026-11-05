import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const USERS = {
  admin: "admin@empresa-exemplo.com.br", analista: "analista@empresa-exemplo.com.br", auditor: "auditor@empresa-exemplo.com.br",
  leitura: "leitura@empresa-exemplo.com.br", vazia: "admin@empresa-vazia.example.com", suspensa: "admin@empresa-suspensa.example.com",
};

export async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByTestId("who")).toContainText(email);
}

export async function logout(page: Page) {
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);   // espera a navegação terminar antes de um novo login
}

/** Mensagem de erro do formulário (exclui o anunciador de rotas do Next, que também usa role=alert). */
export const formAlert = (page: Page) => page.locator("[role=alert]:not(#__next-route-announcer__)");

/** Chama a API pelo próprio proxy do console, com a sessão do navegador. */
export async function apiGet<T>(page: Page, path: string): Promise<{ data: T; total: number }> {
  const r = await page.request.get(`/api/proxy/${path}`);
  expect(r.ok(), `${path} -> ${r.status()}`).toBeTruthy();
  return { data: (await r.json()) as T, total: Number(r.headers()["x-total-count"] ?? "0") };
}

/** Sem violações sérias ou críticas de acessibilidade (inclui contraste de cor). */
export async function expectAccessible(page: Page, context?: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`), context ?? "acessibilidade").toEqual([]);
}
