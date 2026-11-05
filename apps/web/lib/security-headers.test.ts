import { describe, expect, it } from "vitest";
import { contentSecurityPolicy, securityHeaders } from "./security-headers";

describe("cabeçalhos de segurança", () => {
  const h = Object.fromEntries(securityHeaders(false).map((x) => [x.key, x.value]));
  it("trazem os cabeçalhos esperados", () => {
    for (const k of ["Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security"]) {
      expect(h[k], k).toBeTruthy();
    }
    expect(h["X-Frame-Options"]).toBe("DENY");
  });
  it("a política de conteúdo é restritiva e sem eval em produção", () => {
    const csp = contentSecurityPolicy(false);
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/https?:\/\//);          // nenhum domínio externo liberado
    expect(contentSecurityPolicy(true)).toContain("unsafe-eval");   // só no desenvolvimento
  });
});
