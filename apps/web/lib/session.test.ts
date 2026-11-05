import { describe, expect, it } from "vitest";
import { cookieMaxAge, jwtExp } from "./session";

const jwt = (payload: object) => `x.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.y`;

describe("sessão", () => {
  it("lê o exp do JWT (sem validar: quem valida é a API)", () => {
    expect(jwtExp(jwt({ exp: 1000 }))).toBe(1000);
    expect(jwtExp("lixo")).toBeNull();
    expect(jwtExp(jwt({}))).toBeNull();
  });
  it("a validade do cookie acompanha o token, no máximo 12 h", () => {
    expect(cookieMaxAge(jwt({ exp: 1600 }), 3600, 1000)).toBe(600);
    expect(cookieMaxAge(jwt({ exp: 1_000_000 }), 3600, 1000)).toBe(12 * 3600);
    expect(cookieMaxAge(jwt({ exp: 500 }), 3600, 1000)).toBe(0);
    expect(cookieMaxAge("lixo", 1234)).toBe(1234);
  });
});
