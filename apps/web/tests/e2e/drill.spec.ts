import { expect, test, type Page } from "@playwright/test";
import { apiGet, login, USERS } from "./helpers";

const INJ = "injection_direta,injection_indireta,jailbreak,extracao_system_prompt";
const total = async (page: Page, params: string) => (await apiGet<unknown[]>(page, `v1/events?limit=1&${params}`)).total;
const shown = (page: Page) => page.getByTestId("total");

test("painel clicável: cada indicador abre os prompts que formam o número, com os mesmos filtros da API", async ({ page }) => {
  await login(page, USERS.admin);
  const cases: [string, string, string][] = [               // [rótulo do indicador, trecho esperado na URL, filtros equivalentes na API]
    ["Prompts analisados", "days=14", "days=14"],
    ["Alto risco", "min_score=50", "days=14&min_score=50"],
    ["Com dado sensível", "has_sensitive=true", "days=14&has_sensitive=true"],
    ["Credenciais detectadas", "category=segredo", "days=14&category=segredo"],
    ["Dados pessoais", "category=pii", "days=14&category=pii"],
    ["Prompt injection suspeita", `category=${INJ.replaceAll(",", "%2C")}`, `days=14&category=${INJ}`],
    ["Com código", "has_code=true", "days=14&has_code=true"],
  ];
  for (const [label, urlPart, api] of cases) {
    await page.goto("/");
    await page.getByTestId("kpi").filter({ hasText: label }).click();
    await expect(page).toHaveURL(new RegExp(`/history\\?.*${urlPart}`));
    const n = await total(page, api);
    await expect(shown(page)).toHaveText(new RegExp(`^${n} resultado`));                   // o número do painel = a lista que abre
    if (label === "Alto risco") await expect(page.getByTestId("drill-filters")).toContainText("score ≥ 50");
  }
  await page.goto("/");
  await page.getByTestId("kpi").filter({ hasText: "Usuários ativos" }).click();
  await expect(page).toHaveURL(/\/risk/);
});

test("painel clicável: barras, ferramentas, departamentos, categorias, usuários e meses também abrem os prompts filtrados", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/");
  await expect(page.getByTestId("kpi").first()).toBeVisible();

  // ferramenta (uso por ferramenta)
  const toolLink = page.getByRole("list", { name: "Uso por ferramenta" }).getByRole("link").first();
  await toolLink.click();
  await expect(page).toHaveURL(/\/history\?.*app=/);
  const app = new URL(page.url()).searchParams.get("app")!;
  await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `days=14&app=${app}`)} resultado`));

  // departamento (alto risco por departamento)
  await page.goto("/");
  const dept = page.getByRole("list", { name: "Alto risco por departamento" }).getByRole("link").first();
  await dept.click();
  await expect(page).toHaveURL(/\/history\?/);
  const u = new URL(page.url());
  expect(u.pathname).toBe("/history");
  expect(u.searchParams.get("min_score")).toBe("50");
  await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `days=14&min_score=50&department=${encodeURIComponent(u.searchParams.get("department")!)}`)} resultado`));

  // categoria mais frequente
  await page.goto("/");
  await page.getByRole("list", { name: "Categorias mais frequentes" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/history\?.*category=/);
  const cat = new URL(page.url()).searchParams.get("category")!;
  await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `days=14&category=${cat}`)} resultado`));

  // usuário com mais alertas
  await page.goto("/");
  const user = page.getByRole("list", { name: "Usuários com mais alertas" }).getByRole("link").first();
  if (await user.count()) {
    await user.click();
    await expect(page).toHaveURL(/\/history\?.*user=/);
    const q = new URL(page.url()).searchParams;
    await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `days=14&min_score=25&user_q=${encodeURIComponent(q.get("user")!)}`)} resultado`));
  }

  // barra do gráfico de alto risco por dia
  await page.goto("/");
  const bars = page.getByRole("link", { name: /abrir os [1-9]\d* prompts de alto risco/ });
  if (await bars.count()) {
    await bars.first().click();
    await expect(page).toHaveURL(/\/history\?.*date_from=/);
    const q = new URL(page.url()).searchParams;
    expect(q.get("date_from")).toBe(q.get("date_to"));
    await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `date_from=${q.get("date_from")}&date_to=${q.get("date_to")}&min_score=50`)} resultado`));
  }

  // mês (evolução mensal)
  await page.goto("/");
  const month = page.getByTestId("monthly").getByRole("link").first();
  await month.click();
  await expect(page).toHaveURL(/\/history\?.*date_from=/);
  const m = new URL(page.url()).searchParams;
  await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, `date_from=${m.get("date_from")}&date_to=${m.get("date_to")}`)} resultado`));
});

test("filtros da URL inválidos são ignorados (nada quebra nem é injetado)", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/history?days=999999&category=segredo%3BDROP&severity=xx&min_score=500&date_from=ontem&has_code=talvez");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Todos os prompts");
  await expect(page.getByTestId("drill-filters")).toHaveCount(0);
  await expect(shown(page)).toHaveText(new RegExp(`^${await total(page, "days=30")} resultado`));
});
