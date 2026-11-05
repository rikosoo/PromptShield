import { describe, expect, it } from "vitest";
import { licenseNotice, STATE_EFFECT, STATE_LABEL } from "./license";
import type { LicenseStatus } from "./types";

const base: LicenseStatus = { mode: "onprem", state: "ativo", message: "ok", can_enroll: true, inspecting: true };

describe("licenseNotice", () => {
  it("sem faixa quando está ativo ou o licenciamento está desligado", () => {
    expect(licenseNotice(undefined)).toBeNull();
    expect(licenseNotice({ ...base, mode: "off", state: "encerrado", inspecting: false })).toBeNull();
    expect(licenseNotice(base)).toBeNull();
  });
  it("ativo só avisa nos últimos 30 dias do contrato, e nunca depois de vencido (aí o estado muda)", () => {
    const now = new Date("2026-11-02T12:00:00Z");
    const at = (days: number) => ({ ...base, contract_end: new Date(now.getTime() + days * 86_400_000).toISOString() });
    expect(licenseNotice(at(200), now)).toBeNull();
    expect(licenseNotice(at(31), now)).toBeNull();
    expect(licenseNotice(at(30), now)?.level).toBe("warn");
    expect(licenseNotice(at(30), now)?.text).toContain("30 dias");
    expect(licenseNotice(at(1), now)?.text).toContain("1 dia.");
    expect(licenseNotice(at(0), now)?.text).toContain("hoje");
    expect(licenseNotice(at(-1), now)).toBeNull();
    expect(licenseNotice({ ...base, contract_end: null }, now)).toBeNull();
    expect(licenseNotice({ ...at(10), mode: "off" }, now)).toBeNull();
  });
  it("cada estado tem a gravidade certa e leva à página da licença", () => {
    const lvl = (state: LicenseStatus["state"], inspecting = true) => licenseNotice({ ...base, state, inspecting, can_enroll: false })?.level;
    expect(lvl("sem_contato")).toBe("warn");
    expect(lvl("em_tolerancia")).toBe("warn");
    expect(lvl("expirado")).toBe("crit");
    expect(lvl("nao_ativado", false)).toBe("crit");
    expect(lvl("encerrado")).toBe("crit");
    expect(licenseNotice({ ...base, state: "expirado" })?.href).toBe("/license");
  });
  it("encerrado diz com todas as letras quando a inspeção parou", () => {
    expect(licenseNotice({ ...base, state: "encerrado", inspecting: false })?.title).toContain("inspeção parada");
    expect(licenseNotice({ ...base, state: "encerrado", inspecting: true })?.title).not.toContain("parada");
  });
  it("todo estado tem rótulo e efeito descritos, e nenhum promete apagar dados", () => {
    for (const k of Object.keys(STATE_LABEL) as (keyof typeof STATE_LABEL)[]) {
      expect(STATE_LABEL[k].length).toBeGreaterThan(2);
      expect(STATE_EFFECT[k]).not.toMatch(/apag/i);
    }
  });
});
