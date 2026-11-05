export const SESSION_COOKIE = "ps_session";
export const OIDC_COOKIE = "ps_oidc";

/** Decodifica o `exp` de um JWT sem verificar assinatura. Só para definir a validade do cookie; quem valida é a API. */
export function jwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

export function cookieMaxAge(token: string, fallbackSeconds = 3600, nowSeconds = Math.floor(Date.now() / 1000)): number {
  const exp = jwtExp(token);
  if (exp === null) return fallbackSeconds;
  return Math.max(0, Math.min(exp - nowSeconds, 12 * 3600));
}

export const apiBase = () => (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");
export const authMode = () => (process.env.AUTH_MODE === "mock" ? "mock" : "oidc");
export const secureCookies = () => (process.env.PUBLIC_BASE_URL ?? "").startsWith("https://");
