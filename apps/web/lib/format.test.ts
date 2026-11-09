import { describe, expect, it } from "vitest";
import { clip, pct, splitMasks } from "./format";
import { severityOf } from "./labels";

describe("splitMasks", () => {
  it("destaca as máscaras da API e preserva o resto", () => {
    const parts = splitMasks("Cliente CPF ***.***.***-25 e chave AKIA**** em [CPF]");
    expect(parts.filter((p) => p.mask).map((p) => p.text)).toEqual(["***.***.***-25", "AKIA****", "[CPF]"]);
    expect(parts.map((p) => p.text).join("")).toBe("Cliente CPF ***.***.***-25 e chave AKIA**** em [CPF]");
  });
  it("texto sem máscara fica inteiro", () => expect(splitMasks("oi")).toEqual([{ text: "oi", mask: false }]));
});

describe("formatação", () => {
  it("clip e pct", () => {
    expect(clip("abcdef", 4)).toBe("abc…");
    expect(clip("abc", 4)).toBe("abc");
    expect(pct(0.974)).toBe("97%");
  });
  it("severidade segue a régua da API", () => {
    expect([0, 24, 25, 49, 50, 69, 70, 100].map(severityOf)).toEqual(["baixo", "baixo", "medio", "medio", "alto", "alto", "critico", "critico"]);   // faixas do motor 2.0: 0-24, 25-49, 50-69, 70-100
  });
});

describe("realce das máscaras com final do valor", () => {
  it("destaca [TOKEN ****5Yw1], [BOLETO ****5000] e AKIA****R3TN inteiros", () => {
    const parts = (t: string) => splitMasks(t).filter((p) => p.mask).map((p) => p.text);
    expect(parts("meu token é [TOKEN ****5Yw1] ok")).toEqual(["[TOKEN ****5Yw1]"]);
    expect(parts("pague [BOLETO ****5000] hoje")).toEqual(["[BOLETO ****5000]"]);
    expect(parts("chave AKIA****R3TN no deploy")).toEqual(["AKIA****R3TN"]);
    expect(parts("texto comum sem máscara")).toEqual([]);
  });
});
