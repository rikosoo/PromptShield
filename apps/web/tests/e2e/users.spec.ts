import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, login, USERS } from "./helpers";

interface Person { user_id: string; events: number }

test("aba Usuários: procurar por pessoa (contém e começa com) e ver todos os prompts dela", async ({ page }) => {
  await login(page, USERS.admin);
  const people = (await apiGet<Person[]>(page, "v1/people?days=365&limit=200")).data;
  expect(people.length).toBeGreaterThan(0);
  const who = people[0];
  await page.goto("/users");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Usuários");
  await expectAccessible(page);

  const table = page.getByTestId("users-table");
  await page.getByLabel("Período").selectOption("365");
  await expect(table.getByRole("button", { name: who.user_id, exact: true })).toBeVisible();

  // começa com: o começo do identificador acha a pessoa; um meio de identificador não
  await page.getByLabel("Como procurar").selectOption("prefix");
  await page.getByLabel("Procurar", { exact: true }).fill(who.user_id.slice(0, 3));
  await expect(table.getByRole("button", { name: who.user_id, exact: true })).toBeVisible();
  const startsWith = people.filter((p) => p.user_id.toLowerCase().startsWith(who.user_id.slice(0, 3).toLowerCase())).length;
  await expect.poll(async () => await table.getByRole("button").count()).toBe(startsWith);

  // abrir a pessoa mostra todos os prompts dela (e só dela)
  await table.getByRole("button", { name: who.user_id, exact: true }).click();
  const prompts = page.getByTestId("user-prompts");
  await expect(prompts.getByRole("button", { name: /Ver detalhes/ }).first()).toBeVisible();
  const detail = (await apiGet<{ user_id: string }[]>(page, `v1/events?user_id=${encodeURIComponent(who.user_id)}&days=365&limit=15`));
  expect(detail.total).toBe(who.events);
  await prompts.getByRole("button", { name: /Ver detalhes/ }).first().click();
  await expect(page.getByTestId("prompt-detail")).toBeVisible();
  await page.getByRole("button", { name: "Fechar" }).first().click();

  // sem resultado
  await page.getByLabel("Procurar", { exact: true }).fill("zzzz-ninguem");
  await expect(page.getByText(/Ninguém encontrado/)).toBeVisible();
});

test("menu: seções expandem e recolhem", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/users");
  const nav = page.getByRole("navigation", { name: "Principal" });
  const section = nav.getByRole("button", { name: /Incidentes/ });
  await expect(section).toHaveAttribute("aria-expanded", "true");
  await expect(nav.getByRole("link", { name: "Alertas e SIEM" })).toBeVisible();
  await section.click();
  await expect(section).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Alertas e SIEM" })).toBeHidden();
  await expect(nav.getByRole("link", { name: "Usuários", exact: true })).toBeVisible();      // a seção da página atual segue aberta
  await page.reload();
  await expect(nav.getByRole("button", { name: /Incidentes/ })).toHaveAttribute("aria-expanded", "false");   // lembra no navegador
  await nav.getByRole("button", { name: /Incidentes/ }).click();
  await expect(nav.getByRole("link", { name: "Alertas e SIEM" })).toBeVisible();
});

test("grupos: escolher pessoas na lista, selecionar todas as que começam com um texto e tirar uma só", async ({ page }) => {
  await login(page, USERS.admin);
  const people = (await apiGet<Person[]>(page, "v1/people?days=365&limit=200")).data;
  expect(people.length).toBeGreaterThan(1);
  const prefix = people[0].user_id.slice(0, 2);
  const expected = people.filter((p) => p.user_id.toLowerCase().startsWith(prefix.toLowerCase())).map((p) => p.user_id);
  const group = `lote-${Date.now().toString(36)}`;
  await page.goto("/groups");
  await page.getByLabel("Nome do grupo").fill(group);
  await page.getByRole("button", { name: "Criar grupo" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Grupo criado" })).toBeVisible();

  const picker = page.getByTestId("picker");
  await picker.getByLabel("Como procurar").selectOption("prefix");
  await picker.getByLabel("Procurar", { exact: true }).fill(prefix);
  await expect(picker.getByTestId("candidates").getByRole("checkbox")).toHaveCount(expected.length);
  await picker.getByRole("button", { name: /Selecionar todos os resultados/ }).click();
  await picker.getByRole("button", { name: /Adicionar selecionados \(\d+\)/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "adicionadas ao grupo" })).toBeVisible();
  for (const id of expected) await expect(page.getByTestId("members").getByText(id, { exact: true })).toBeVisible();

  // quem já está no grupo sai da lista de escolha; tirar uma pessoa só
  await expect(picker.getByTestId("candidates")).toHaveCount(0);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: `Tirar ${expected[0]} do grupo` }).click();
  await expect(page.getByRole("status").filter({ hasText: "Pessoa removida do grupo" })).toBeVisible();
  await expect(page.getByTestId("members").getByText(expected[0], { exact: true })).toHaveCount(0);
  const g = (await apiGet<{ name: string; members: number }[]>(page, "v1/groups")).data.find((x) => x.name === group);
  expect(g?.members).toBe(expected.length - 1);
  await expectAccessible(page);
});
