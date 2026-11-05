import { describe, expect, it } from "vitest";
import { parseIds } from "./groups";

describe("parseIds", () => {
  it("separa por linha, vírgula e ponto e vírgula, sem vazios nem repetidos", () => {
    expect(parseIds("ana\nbia, caio;ana\n\n  \n dani ")).toEqual(["ana", "bia", "caio", "dani"]);
    expect(parseIds("")).toEqual([]);
    expect(parseIds(" , ; \n")).toEqual([]);
  });
  it("não mexe em e-mails ou nomes com espaço interno", () => {
    expect(parseIds("ana.silva@empresa.com.br\nJoão da Silva")).toEqual(["ana.silva@empresa.com.br", "João da Silva"]);
  });
});
