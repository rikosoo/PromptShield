import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, login, USERS } from "./helpers";

// A API de atualizações e a de licença são SIMULADAS aqui (page.route): o servidor de teste roda com LICENSE_MODE=off.
// A lógica real (aviso assinado, download conferido, sombra→ativo) é provada em apps/api/tests/test_updates_onprem.py.
const status = { mode: "onprem", state: "ativo", message: "Licença ativa.", can_enroll: true, inspecting: true, max_devices: 10, customer: "Empresa Exemplo (simulado)" };

async function mock(page: Page) {
  const st = {
    app: { version: "0.4.0", security: true, notes: "Corrige uma falha (simulado)", size: 3_000_000, sha256: "ab".repeat(32), file: "promptshield-onprem-0.4.0.zip", status: "available", error: null, approved_by: null, approved_at: null, ready_at: null } as Record<string, unknown>,
    pack: { id: "11111111-1111-1111-1111-111111111111", version: "2026.11.1", status: "staged", notes: "", received_at: new Date().toISOString(), activated_by: null, promoted_at: null, rules: 1, weights: {}, hits: 0 } as Record<string, unknown>,
  };
  const calls: string[] = [];
  await page.route("**/api/proxy/v1/license/status", (r) => r.fulfill({ json: status }));
  await page.route("**/api/proxy/v1/updates", (r) => r.fulfill({ json: { mode: "onprem", app: { installed: "0.3.0", notice: st.app, ready_path: null }, rules: { installed: null, live: null, notice: null }, packs: [st.pack] } }));
  await page.route("**/api/proxy/v1/updates/app/approve", (r) => { calls.push("approve"); st.app = { ...st.app, status: "ready", approved_by: "admin@exemplo.test", approved_at: new Date().toISOString() }; return r.fulfill({ json: { ok: true } }); });
  await page.route("**/api/proxy/v1/rule-packs/*/phase", (r) => { const to = JSON.parse(r.request().postData() ?? "{}").to; calls.push(to); st.pack = { ...st.pack, status: to }; return r.fulfill({ json: { ok: true } }); });
  await page.route("**/api/proxy/v1/rule-packs/1111*", (r) => r.fulfill({ json: { id: st.pack.id, version: "2026.11.1", status: st.pack.status, notes: "", weights: { segredo: 95 }, rules: [{ id: "x", category: "segredo", rule: "Token interno (simulado)", kind: "regex", hits_shadow: 2, hits_active: 0, last_hit: null }] } }));
  return calls;
}

test("atualizações: faixa, aprovar download, instruções de instalação e fases do pacote de regras", async ({ page }) => {
  const calls = await mock(page);
  await login(page, USERS.admin);
  await expect(page.getByTestId("updates-notice")).toContainText("0.4.0");
  await page.getByRole("link", { name: "Ver atualizações" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Atualizações");
  await expect(page.getByTestId("app-installed")).toContainText("0.3.0");
  await expect(page.getByTestId("app-notice")).toContainText("correção de segurança");
  await page.getByRole("button", { name: "Aprovar o download" }).click();
  await expect(page.getByTestId("app-ready")).toContainText("./atualizar.sh");
  await expect(page.getByTestId("app-ready")).toContainText("ab".repeat(32));
  await page.getByRole("button", { name: "Iniciar sombra" }).click();
  await expect(page.getByTestId("pack")).toContainText("Em sombra");
  await page.getByRole("button", { name: "Ver regras" }).click();
  await expect(page.getByTestId("pack-detail")).toContainText("Token interno (simulado)");
  await page.getByRole("button", { name: "Promover a ativo" }).click();
  await expect(page.getByTestId("pack")).toContainText("Ativo");
  await page.getByRole("button", { name: "Desativar" }).click();
  await expect(page.getByTestId("pack")).toContainText("Desativado");
  expect(calls).toEqual(["approve", "shadow", "active", "retired"]);
  await expectAccessible(page, "atualizações");
});

test("atualizações: só o administrador vê o item e a página", async ({ page }) => {
  await mock(page);
  await login(page, USERS.leitura);
  await expect(page.getByRole("link", { name: "Atualizações" })).toHaveCount(0);
  await expect(page.getByTestId("updates-notice")).toHaveCount(0);
  await page.goto("/updates");
  await expect(page.getByText("Só o administrador acessa")).toBeVisible();
});
