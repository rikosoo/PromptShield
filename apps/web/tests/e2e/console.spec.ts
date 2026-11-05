import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, login, logout, USERS } from "./helpers";

// Valores esperados SEMPRE vêm da API (pelo proxy do console) no momento do teste: nada é digitado aqui.
interface Overview { totals: { events: number; high_risk: number; with_code: number; with_sensitive: number; users: number }; daily: { events: number; high_risk: number }[]; by_department: { department: string; events: number; high_risk: number }[] }

test("login, selo de dados de exemplo e proteção de rotas", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);                                  // sem sessão, volta ao login
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("ninguem@nao-existe.example.com");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("usuário não cadastrado ou inativo")).toBeVisible();
  await login(page, USERS.admin);
  await expect(page.getByTestId("demo-badge")).toHaveText("dados de exemplo");
  const tenant = (await apiGet<{ name: string; is_demo: boolean }>(page, "v1/tenant")).data;
  expect(tenant.is_demo).toBe(true);
  await expect(page.getByTestId("tenant-name")).toHaveText(tenant.name);     // o nome vem da API
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/prompts");
  await expect(page).toHaveURL(/\/login/);
});

test("outro tenant: sem selo, sem dados do primeiro", async ({ page }) => {
  await login(page, USERS.vazia);
  await expect(page.getByTestId("demo-badge")).toHaveCount(0);
  await expect(page.getByTestId("tenant-name")).toHaveText("Empresa Vazia Ltda.");
  await expect(page.getByTestId("kpi").first()).toContainText("0");
  await page.goto("/prompts");
  await expect(page.getByText("Nenhum prompt com esses filtros.")).toBeVisible();
  expect((await apiGet<unknown[]>(page, "v1/incidents")).data).toEqual([]);
});

test("visão geral: indicadores iguais aos da API", async ({ page }) => {
  await login(page, USERS.analista);
  const o = (await apiGet<Overview>(page, "v1/stats/overview?days=14")).data;
  const kpi = (label: string) => page.getByTestId("kpi").filter({ hasText: label }).locator("div").first();
  await expect(kpi("Prompts capturados")).toHaveText(String(o.totals.events));
  await expect(kpi("Alto risco")).toHaveText(String(o.totals.high_risk));
  await expect(kpi("Com código")).toHaveText(String(o.totals.with_code));
  await expect(kpi("Com dado sensível")).toHaveText(String(o.totals.with_sensitive));
  expect(o.totals.events).toBeGreaterThan(50);
  expect(o.daily.reduce((a, d) => a + d.events, 0)).toBe(o.totals.events);
  await expect(page.getByRole("img", { name: /Eventos de alto risco por dia/ })).toBeVisible();
  const dept = page.getByRole("list", { name: "Alto risco por departamento" });
  await expect(dept.getByRole("listitem")).toHaveCount(o.by_department.length);
  await expect(page.getByRole("list", { name: "Uso por ferramenta" })).toContainText("corporativa");
  await expect(page.getByRole("list", { name: "Uso por ferramenta" })).toContainText("pessoal");
  await page.getByLabel("Período").selectOption("7");                          // o período muda os números
  const o7 = (await apiGet<Overview>(page, "v1/stats/overview?days=7")).data;
  await expect(kpi("Prompts capturados")).toHaveText(String(o7.totals.events));
});

test("análise de prompts: ordenação por risco, filtros e painel de categorias", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/prompts");
  const rows = page.getByTestId("prompt-row");
  await expect(rows.first()).toBeVisible();
  const all = await apiGet<{ risk_score: number }[]>(page, "v1/events?sort=risk&days=14&min_score=1&limit=20");
  await expect(page.getByTestId("total")).toHaveText(new RegExp(`^${all.total} resultado`));
  const scores = all.data.map((e) => e.risk_score);
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
  expect(await rows.count()).toBe(all.data.length);

  // painel das categorias: vem da taxonomia da API e filtra a lista ao clicar
  const tax = (await apiGet<{ id: string; nome: string }[]>(page, "v1/taxonomy")).data;
  expect(tax).toHaveLength(30);
  await expect(page.locator("button[aria-pressed]").filter({ hasText: tax[0].nome }).first()).toBeVisible();
  const counts = (await apiGet<Record<string, number>>(page, "v1/stats/categories?days=14")).data;
  const [catId] = Object.entries(counts).sort((a, b) => b[1] - a[1]).find(([id]) => id === "segredo") ?? Object.entries(counts)[0];
  const catName = tax.find((c) => c.id === catId)!.nome;
  await page.locator("button[aria-pressed]").filter({ hasText: new RegExp(`^${catName}\\s+\\d+`) }).click();
  const filtered = await apiGet<unknown[]>(page, `v1/events?sort=risk&days=14&min_score=1&category=${catId}&limit=20`);
  await expect(page.getByTestId("total")).toHaveText(new RegExp(`^${filtered.total} resultado`));
  await expect.poll(async () => rows.count()).toBe(Math.min(20, filtered.total));
  for (const r of await rows.all()) await expect(r).toContainText(catName);
  await page.getByRole("button", { name: "Limpar" }).click();
  await expect(page.getByTestId("total")).toHaveText(new RegExp(`^${all.total} resultado`));

  // filtros por caixa de seleção
  for (const [label, param] of [["Contém código", "has_code=true"], ["Dado sensível", "has_sensitive=true"], ["Ação de agente", "agent_action=true"], ["Só bloqueados (ou que seriam)", "only_blocked=true"]] as const) {
    await page.getByLabel(label).check();
    const exp = await apiGet<unknown[]>(page, `v1/events?sort=risk&days=14&min_score=1&${param}&limit=20`);
    await expect(page.getByTestId("total")).toHaveText(new RegExp(`^${exp.total} resultado`));
    expect(exp.total).toBeGreaterThan(0);
    await page.getByLabel(label).uncheck();
  }

  // detalhe: texto mascarado, sem os valores brutos do demo
  await rows.first().getByRole("button").first().click();
  const detail = page.getByTestId("prompt-detail");
  await expect(detail).toContainText("Motivos do score");
  await expect(detail).toContainText("Indicador de risco, requer revisão humana");
  await expectAccessible(page, "detalhe do prompt (diálogo)");
  const body = await page.locator("body").innerText();
  for (const raw of ["S3nh4Fort3x", "AKIAZ7QW4XK2M9PLR3TN", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "4111 1111 1111 1111"]) expect(body).not.toContain(raw);
});

test("incidentes: fila, detalhe com linha do tempo, triagem e texto original com justificativa", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/incidents");
  const list = (await apiGet<{ id: string; severity: string }[]>(page, "v1/incidents?limit=100")).data;
  expect(list.length).toBeGreaterThan(5);
  await expect(page.getByTestId("incident-row")).toHaveCount(list.length);
  await page.getByLabel("Severidade").selectOption("critico");
  const crit = (await apiGet<unknown[]>(page, "v1/incidents?severity=critico&limit=100")).data;
  await expect(page.getByTestId("incident-row")).toHaveCount(crit.length);
  await page.getByLabel("Severidade").selectOption("");

  await page.getByTestId("incident-row").first().getByRole("link").click();
  await expect(page).toHaveURL(/\/incidents\/[0-9a-f-]{36}/);
  const id = page.url().split("/").pop()!;
  const inc = (await apiGet<{ timeline: unknown[]; recommendations: string[]; masked_text: string; has_original: boolean }>(page, `v1/incidents/${id}`)).data;
  await expect(page.getByTestId("timeline").getByRole("listitem")).toHaveCount(inc.timeline.length);
  await expect(page.getByTestId("recommendations").getByRole("listitem")).toHaveCount(inc.recommendations.length);
  await expect(page.getByTestId("evidence")).toBeVisible();
  expect(inc.has_original).toBe(true);

  // triagem: status e responsável, com registro na linha do tempo
  const before = inc.timeline.length;
  await page.getByLabel("Status").selectOption("em analise");
  await expect(page.getByText("Incidente atualizado.")).toBeVisible();
  await page.getByLabel("Responsável").selectOption({ label: "Analista" });
  await expect(page.getByTestId("timeline").getByRole("listitem")).toHaveCount(before + 2);
  await expect(page.getByTestId("timeline")).toContainText("status: em analise");
  await expectAccessible(page, "detalhe do incidente");

  // texto original: exige justificativa, que fica na auditoria
  await page.getByRole("button", { name: "Ver texto original" }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByRole("button", { name: "Ver texto original" })).toBeDisabled();
  await dlg.getByLabel(/Justificativa/).fill("curto");
  await expect(dlg.getByRole("button", { name: "Ver texto original" })).toBeDisabled();
  await dlg.getByLabel(/Justificativa/).fill("apuração do incidente pela equipe de segurança");
  await expectAccessible(page, "diálogo de justificativa");
  await dlg.getByRole("button", { name: "Ver texto original" }).click();
  await expect(page.getByTestId("original")).toBeVisible();
  await expect(page.getByText("Este acesso foi registrado na auditoria.")).toBeVisible();
  const audit = (await apiGet<{ action: string; detail: { justification?: string } }[]>(page, "v1/audit-log?limit=50")).data;
  expect(audit.some((a) => a.action === "event.original_read" && a.detail.justification === "apuração do incidente pela equipe de segurança")).toBe(true);
});

test("incidentes: leitura e auditor não triam nem pedem o original", async ({ page }) => {
  for (const who of [USERS.leitura, USERS.auditor]) {
    await login(page, who);
    await page.goto("/incidents");
    await page.getByTestId("incident-row").first().getByRole("link").click();
    await expect(page.getByLabel("Status")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Ver texto original" })).toHaveCount(0);
    await logout(page);
  }
});

test("políticas: nascem em monitorar, simulação confere com a API e salva", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/policies");
  const existing = (await apiGet<{ name: string }[]>(page, "v1/policies")).data;
  await expect(page.getByTestId("policy-row")).toHaveCount(existing.length);
  await page.getByRole("button", { name: "Nova política" }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByLabel("Monitorar")).toBeChecked();                    // padrão seguro
  await expect(dlg.getByLabel("Aplicar")).not.toBeChecked();
  await dlg.getByLabel("Nome", { exact: true }).fill("Teste: bloquear dados pessoais");
  await dlg.getByLabel("Ação", { exact: true }).selectOption("block");
  await dlg.getByLabel("Dados pessoais").check();
  await dlg.getByLabel("Simular sobre os últimos").selectOption("30");
  await dlg.getByRole("button", { name: "Simular" }).click();
  const matched = Number(await page.getByTestId("sim-matched").innerText());
  const apiSim = await page.request.post("/api/proxy/v1/policies/simulate", {
    headers: { "X-Requested-With": "promptshield", Origin: "http://127.0.0.1:3099", "Content-Type": "application/json" },
    data: { policy: { name: "x", action: "block", mode: "monitor", enabled: true, scope: {}, match: { categories: ["pii"], min_score: 0 } }, days: 30 },
  });
  expect(apiSim.ok()).toBeTruthy();
  expect(matched).toBe((await apiSim.json()).matched);
  expect(matched).toBeGreaterThan(0);
  await expectAccessible(page, "editor de política");
  await dlg.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByTestId("policy-row")).toHaveCount(existing.length + 1);
  const row = page.getByTestId("policy-row").filter({ hasText: "Teste: bloquear dados pessoais" });
  await expect(row).toContainText("monitorar");
  await expect(row).toContainText("Bloquear");
  await expect((await apiGet<{ mode: string; name: string }[]>(page, "v1/policies")).data.find((p) => p.name.startsWith("Teste:"))!.mode).toBe("monitor");
  // alterar para aplicar vira versão 2 e entra na auditoria
  await row.getByRole("button", { name: "Editar" }).click();
  await page.getByRole("dialog").getByLabel("Aplicar").check();
  await page.getByRole("dialog").getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByTestId("policy-row").filter({ hasText: "Teste: bloquear dados pessoais" })).toContainText("aplicar");
  const log = (await apiGet<{ action: string }[]>(page, "v1/audit-log?limit=20")).data;
  expect(log.filter((a) => a.action.startsWith("policy.")).length).toBeGreaterThanOrEqual(2);
});

test("políticas: analista consulta e simula, mas não cria", async ({ page }) => {
  await login(page, USERS.analista);
  await page.goto("/policies");
  await expect(page.getByRole("button", { name: "Nova política" })).toHaveCount(0);
  await page.getByTestId("policy-row").first().getByRole("button", { name: "Ver e simular" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Salvar" })).toHaveCount(0);
  await page.getByRole("dialog").getByRole("button", { name: "Simular" }).click();
  await expect(page.getByTestId("simulation")).toBeVisible();
});

test("acessibilidade: páginas principais, tema escuro e navegação por teclado", async ({ page }) => {
  await page.goto("/login");
  await expectAccessible(page, "login");
  await login(page, USERS.admin);
  for (const path of ["/", "/prompts", "/incidents", "/policies"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page, path);
  }
  await page.goto("/prompts");
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expectAccessible(page, "tema escuro em /prompts");
  await page.getByRole("button", { name: "Tema escuro" }).click();

  // teclado: Tab chega ao link de pular, navegação e filtros; Enter abre o detalhe; Esc fecha o diálogo
  await page.goto("/prompts");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();      // o shell já carregou
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();
  const rowBtn = page.getByTestId("prompt-row").first().getByRole("button").first();
  await rowBtn.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("prompt-detail")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(rowBtn).toBeFocused();                                        // o foco volta ao botão que abriu
  await page.goto("/policies");
  await page.getByRole("button", { name: "Nova política" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("tablet (768 px): sem rolagem horizontal da página", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await login(page, USERS.admin);
  for (const path of ["/", "/prompts", "/incidents", "/policies"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("cabeçalhos de segurança e nenhuma violação da política de conteúdo", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text()); });
  page.on("pageerror", (e) => violations.push(e.message));
  const r = await page.goto("/login");
  const h = r!.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("no-referrer");
  expect(h["x-powered-by"]).toBeUndefined();
  await login(page, USERS.admin);
  for (const path of ["/", "/prompts", "/incidents", "/policies", "/risk", "/alerts", "/reports", "/inference-hooks"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  const api = await page.request.get("/api/proxy/v1/me");
  expect(api.headers()["content-security-policy"]).toBeTruthy();   // também nas rotas da API do console
  expect(violations).toEqual([]);
});
