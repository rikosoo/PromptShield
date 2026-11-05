import { describe, expect, it } from "vitest";
import { contractNotice } from "./contract";
import type { Contract } from "./types";

const base: Contract = { suspended: false, suspended_at: null, suspended_reason: null, license_expires_at: null, days_to_expiry: null, expired: false };

describe("contractNotice", () => {
  it("sem aviso quando está tudo certo ou sem validade", () => {
    expect(contractNotice(undefined)).toBeNull();
    expect(contractNotice(base)).toBeNull();
    expect(contractNotice({ ...base, license_expires_at: "2027-01-01T00:00:00Z", days_to_expiry: 120 })).toBeNull();
  });
  it("avisa 15 dias antes, no singular e no dia", () => {
    expect(contractNotice({ ...base, days_to_expiry: 15 })?.level).toBe("warn");
    expect(contractNotice({ ...base, days_to_expiry: 1 })?.text).toContain("1 dia.");
    expect(contractNotice({ ...base, days_to_expiry: 0 })?.text).toContain("hoje");
    expect(contractNotice({ ...base, days_to_expiry: 16 })).toBeNull();
  });
  it("vencida é crítica e diz o que continua funcionando", () => {
    const n = contractNotice({ ...base, expired: true, days_to_expiry: -3 });
    expect(n?.level).toBe("crit");
    expect(n?.text).toContain("continuam enviando");
  });
  it("suspensa tem prioridade, mostra o motivo e garante que os dados ficam", () => {
    const n = contractNotice({ ...base, suspended: true, expired: true, suspended_reason: "fatura em atraso" });
    expect(n?.title).toBe("Contrato suspenso");
    expect(n?.text).toContain("fatura em atraso");
    expect(n?.text).toContain("continuam guardados");
  });
});
