import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, formAlert, login, USERS } from "./helpers";

interface Group { name: string; members: number }
interface Exc { user_id: string | null; group: string | null; state: string }
interface Allow { value: string }

test("grupos, exceções e domínios permitidos: administrador cria, API confirma, leitura só consulta", async ({ page }) => {
  const tag = Date.now().toString(36);
  const group = `grupo-${tag}`;
  const host = `parceiro-${tag}.example.com`;
  await login(page, USERS.admin);

  // grupos
  await page.goto("/groups");
  await page.getByLabel("Nome do grupo").fill(group);
  await page.getByRole("button", { name: "Criar grupo" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Grupo criado" })).toBeVisible();
  await page.getByLabel(/Identificadores/).fill("ana.sintetica\nbia.sintetica, ana.sintetica");
  await page.getByRole("button", { name: "Adicionar" }).click();
  await expect(page.getByTestId("members").getByText("bia.sintetica")).toBeVisible();
  const groups = (await apiGet<Group[]>(page, "v1/groups")).data;
  expect(groups.find((g) => g.name === group)?.members).toBe(2);               // o repetido não conta duas vezes
  await expectAccessible(page);

  // exceção por grupo (só grupo cadastrado) e por pessoa
  await page.goto("/exceptions");
  await page.getByLabel("Política").selectOption({ index: 1 });
  await page.getByLabel("um grupo").check();
  await page.getByLabel("Grupo", { exact: true }).selectOption(group);
  await page.getByLabel(/Motivo/).fill("equipe sintética de resposta a incidentes");
  await page.getByRole("button", { name: "Criar exceção" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Exceção criada" })).toBeVisible();
  await expect(page.getByTestId("exceptions-table").getByText(group)).toBeVisible();
  await page.getByLabel("uma pessoa").check();
  await page.getByLabel("Identificador da pessoa").fill("ana.sintetica");
  await page.getByLabel(/Motivo/).fill("curto");
  await expect(page.getByRole("button", { name: "Criar exceção" })).toBeDisabled();   // motivo curto nem envia
  const exc = (await apiGet<Exc[]>(page, "v1/exceptions?only_active=true")).data;
  expect(exc.filter((x) => x.group === group && x.state === "vigente")).toHaveLength(1);
  await expectAccessible(page);

  // domínios permitidos
  await page.goto("/allowlist");
  await page.getByLabel(/Domínio \(sem/).fill("https://errado.com/x");
  await page.getByRole("button", { name: "Permitir" }).click();
  await expect(formAlert(page).filter({ hasText: /sem http/ })).toBeVisible();          // o servidor recusa e a mensagem aparece
  await page.getByLabel(/Domínio \(sem/).fill(host);
  await page.getByRole("button", { name: "Permitir" }).click();
  await expect(page.getByTestId("allowlist-table").getByText(host)).toBeVisible();
  expect((await apiGet<Allow[]>(page, "v1/allowlist")).data.map((a) => a.value)).toContain(host);
  await expect(page.getByRole("note")).toContainText("exfiltração");                    // o aviso do efeito colateral está na tela
  await expectAccessible(page);

  // política: o grupo cadastrado aparece no escopo
  await page.goto("/policies");
  await page.getByRole("button", { name: "Editar" }).first().click();
  await expect(page.getByTestId("scope-groups").getByText(group)).toBeVisible();

  // leitura consulta, mas não vê formulários
  await login(page, USERS.leitura);
  for (const path of ["/groups", "/exceptions", "/allowlist"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: /Criar|Permitir|Adicionar|Revogar|Apagar|Tirar/ })).toHaveCount(0);
  }
  await page.goto("/allowlist");
  await expect(page.getByTestId("allowlist-table").getByText(host)).toBeVisible();
});
