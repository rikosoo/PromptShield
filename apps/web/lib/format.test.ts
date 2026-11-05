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
    expect([0, 29, 30, 59, 60, 79, 80, 100].map(severityOf)).toEqual(["baixo", "baixo", "medio", "medio", "alto", "alto", "critico", "critico"]);
  });
});
