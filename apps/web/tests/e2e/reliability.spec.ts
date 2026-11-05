import { expect, test } from "@playwright/test";
import { apiGet, expectAccessible, login, USERS } from "./helpers";

interface Quality { reviewed: number; min_for_estimate: number; verdicts: { falso_positivo: number } }
interface Devices { devices: { revoked: boolean }[] }

test("visão geral: confiabilidade mostra falso positivo e cobertura dos coletores com os números da API", async ({ page }) => {
  await login(page, USERS.admin);
  const q = (await apiGet<Quality>(page, "v1/feedback/summary?days=14")).data;
  const d = (await apiGet<Devices>(page, "v1/devices")).data;
  const box = page.getByTestId("reliability");
  await expect(box).toBeVisible();
  await expect(box.getByText("Cobertura dos coletores")).toBeVisible();
  const fp = box.getByTestId("fp-rate");
  if (q.reviewed < q.min_for_estimate) await expect(fp).toHaveText("—");   // poucas revisões: não inventa taxa
  else await expect(fp).toHaveText(`${Math.round((q.verdicts.falso_positivo / q.reviewed) * 100)}%`);
  const sensors = d.devices.filter((x) => !x.revoked).length;
  await expect(box.getByTestId("collector-summary")).toContainText(`${sensors} sensor(es)`);
  await expectAccessible(page);
});
