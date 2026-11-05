import { expect, test } from "@playwright/test";
import { expectAccessible, login, logout, USERS } from "./helpers";

test("dispositivos: criar token, matricular uma máquina, ver cobertura e revogar", async ({ page }) => {
  await login(page, USERS.admin);
  await page.goto("/devices");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Dispositivos");
  await expect(page.getByText("Nenhuma máquina matriculada.")).toBeVisible();
  await expect(page.getByTestId("license")).toContainText("Sem limite de máquinas");

  await page.getByLabel("Nome (ex.: piloto TI)").fill("piloto e2e");
  await page.getByRole("button", { name: "Criar token" }).click();
  const token = (await page.getByTestId("new-token").textContent())!.trim();
  expect(token).toMatch(/^pse_[0-9a-f]{8}_/);
  await expect(page.getByTestId("cmd-windows")).toContainText("install.ps1");
  await expect(page.getByTestId("cmd-windows")).toContainText(token);
  await expect(page.getByTestId("cmd-unix")).toContainText("install.sh");
  await expect(page.getByTestId("deploy-command")).toContainText("--confirm-employees-notified");
  await expect(page.getByTestId("deploy-command")).toContainText(token);
  await page.getByRole("button", { name: "Já guardei" }).click();

  // a máquina troca o token por uma chave própria (direto na API, como o instalador faz)
  const r = await page.request.post("http://127.0.0.1:8099/v1/enroll", {
    data: { token, hostname: "NOTE-E2E", os: "Windows", client_version: "0.1", tools: ["claude_code", "github_copilot_cli"] },
  });
  expect(r.status()).toBe(201);
  await page.reload();
  await expect(page.getByTestId("device-row")).toHaveCount(1);
  await expect(page.getByTestId("device-row")).toContainText("NOTE-E2E");
  await expect(page.getByTestId("kpi").filter({ hasText: "Máquinas ativas" })).toContainText("1");
  await expect(page.getByTestId("kpi").filter({ hasText: "GitHub Copilot CLI" })).toBeVisible();
  await expect(page.getByTestId("tokens-table")).toContainText("1 / 1000");
  await expect(page.getByTestId("license")).toContainText("1 ativas");
  await expect(page.getByTestId("device-row").first()).toContainText("sim");
  await expectAccessible(page);

  page.once("dialog", (d) => void d.accept());
  await page.getByTestId("device-row").getByRole("button", { name: "Revogar" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Máquina revogada." })).toBeVisible();
  await expect(page.getByTestId("device-row")).toContainText("revogada");

  await logout(page);
  await login(page, USERS.analista);
  await page.goto("/devices");
  await expect(page.getByText("Só o administrador gerencia tokens.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Criar token" })).toHaveCount(0);
});
