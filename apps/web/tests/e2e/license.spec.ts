import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

// O servidor de teste roda com LICENSE_MODE=off; aqui a API de licença é SIMULADA (page.route) para ver como o console mostra cada estado.
// A lógica real dos estados é testada em packages/licensing e apps/api/tests/test_license_onprem.py.
// datas relativas a HOJE: com data fixa, o teste "licença ativa: sem faixa" quebraria sozinho quando o calendário chegasse perto do fim do contrato
const days = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString();
const base = {
  mode: "onprem", state: "ativo", message: "Licença ativa.", can_enroll: true, inspecting: true, max_devices: 100, customer: "Empresa Exemplo (simulado)",
  installation_id: "0123456789abcdef0123456789abcdef", server_configured: true, serial: 3, on_end: "stop_inspection",
  contract_start: days(-165), contract_end: days(200), tolerance_end: days(215), auth_expires: days(5),
  last_success_at: days(-1), last_attempt_at: days(-1), last_attempt_failed: false, last_error: null,
};

async function mockStatus(page: Page, over: Record<string, unknown>) {
  await page.route("**/api/proxy/v1/license/status", (route) => route.fulfill({ json: { ...base, ...over } }));
}

const CASES = [
  { state: "nao_ativado", inspecting: false, can_enroll: false, title: "Instalação sem ativação", message: "Instalação sem ativação. Informe o código de ativação.", stopped: true },
  { state: "sem_contato", inspecting: true, can_enroll: true, title: "Sem contato com o licenciamento", message: "Sem contato com o serviço de licenças. A autorização local vale por mais 4 dia(s).", stopped: false },
  { state: "em_tolerancia", inspecting: true, can_enroll: true, title: "Contrato vencido, em tolerância", message: "Contrato vencido em 10/01/2027. Em tolerância por mais 9 dia(s).", stopped: false },
  { state: "expirado", inspecting: true, can_enroll: false, title: "Licença expirada", message: "Licença expirada. Novas máquinas não podem ser matriculadas.", stopped: false },
  { state: "suspenso", inspecting: false, can_enroll: false, title: "Licença suspensa: inspeção parada", message: "Licença SUSPENSA: faltou a validação com o fornecedor por mais de 21 dias. A inspeção está PARADA.", stopped: true },
  { state: "encerrado", inspecting: false, can_enroll: false, title: "Contrato encerrado: inspeção parada", message: "Contrato encerrado: a inspeção está PARADA conforme o contrato.", stopped: true },
];

for (const c of CASES) {
  test(`licença ${c.state}: faixa no topo, página com o efeito e a inspeção ${c.stopped ? "PARADA" : "funcionando"}`, async ({ page }) => {
    await mockStatus(page, { state: c.state, inspecting: c.inspecting, can_enroll: c.can_enroll, message: c.message });
    await login(page, USERS.admin);
    const notice = page.getByTestId("license-notice");
    await expect(notice).toContainText(c.title);
    await expect(notice).toContainText(c.message);
    await page.getByRole("link", { name: "Ver a licença" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Licença");
    await expect(page.getByTestId("inspecting")).toContainText(c.stopped ? "Inspeção PARADA" : "Inspeção funcionando");
    await expect(page.getByTestId("license-message")).toContainText(c.message);
    await expect(page.getByTestId("license-details")).toContainText("Empresa Exemplo (simulado)");
    await expect(page.getByTestId("license-details")).toContainText("0123456789abcdef0123456789abcdef");
    await expect(page.getByLabel("Código de ativação (uso único)")).toHaveCount(c.state === "nao_ativado" ? 1 : 0);
    await expectAccessible(page);
  });
}

test("licença ativa: sem faixa; administrador renova, leitura só vê", async ({ page }) => {
  await mockStatus(page, {});
  await login(page, USERS.admin);
  await expect(page.getByTestId("license-notice")).toHaveCount(0);
  await page.goto("/license");
  await expect(page.getByRole("button", { name: "Renovar agora" })).toBeVisible();
  await page.context().clearCookies();
  await login(page, USERS.leitura);
  await page.goto("/license");
  await expect(page.getByTestId("license-details")).toBeVisible();
  await expect(page.getByRole("button", { name: "Renovar agora" })).toHaveCount(0);
});

test("ativação: erro do fornecedor aparece com a mensagem; código curto nem envia", async ({ page }) => {
  await mockStatus(page, { state: "nao_ativado", inspecting: false, can_enroll: false, message: "Instalação sem ativação." });
  await page.route("**/api/proxy/v1/license/activate", (route) =>
    route.fulfill({ status: 400, json: { detail: { code: "code_used", message: "este código já foi usado" } } }));
  await login(page, USERS.admin);
  await page.goto("/license");
  await expect(page.getByRole("button", { name: "Ativar" })).toBeDisabled();
  await page.getByLabel("Código de ativação (uso único)").fill("psa_00000000_codigo-de-teste");
  await page.getByRole("button", { name: "Ativar" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "este código já foi usado" })).toBeVisible();
});

test("licenciamento desligado (SaaS e desenvolvimento): a página explica e não há faixa", async ({ page }) => {
  await login(page, USERS.admin);
  await expect(page.getByTestId("license-notice")).toHaveCount(0);
  await page.goto("/license");
  await expect(page.getByTestId("license-off")).toContainText("LICENSE_MODE=off");
});

test("licença ativa perto do fim do contrato: faixa amarela com os dias e o caminho para a licença", async ({ page }) => {
  await mockStatus(page, { contract_end: days(12.5) });   // meio dia de folga: a página calcula alguns segundos depois e arredonda para baixo
  await login(page, USERS.admin);
  const notice = page.getByTestId("license-notice");
  await expect(notice).toContainText("Contrato perto do fim");
  await expect(notice).toContainText("12 dias");
  await page.getByRole("link", { name: "Ver a licença" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Licença");
});
