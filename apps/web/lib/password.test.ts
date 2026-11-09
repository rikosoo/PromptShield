import { describe, expect, it } from "vitest";
import { passwordOk, passwordRules } from "./password";

describe("política de senha", () => {
  it("aceita as que cumprem tudo", () => {
    for (const p of ["Abcdef1!", "Teste-PS-2026!", "Senha@123", "Ação#Forte9ç"]) expect(passwordOk(p)).toBe(true);
  });
  it("recusa e diz o que falta", () => {
    expect(passwordOk("123456")).toBe(false);
    expect(passwordRules("123456").filter((r) => !r.ok).map((r) => r.id)).toEqual(["len", "lower", "upper", "special"]);
    expect(passwordRules("abcdefgh").filter((r) => !r.ok).map((r) => r.id)).toEqual(["upper", "digit", "special"]);
    expect(passwordRules("Abcdef1 ").find((r) => r.id === "special")!.ok).toBe(false);       // espaço não conta
    expect(passwordOk("A".repeat(129) + "b1!")).toBe(false);
  });
});
