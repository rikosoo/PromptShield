import { createHash, randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { authMode, OIDC_COOKIE, secureCookies } from "@/lib/session";

/** Início do login OIDC (Authorization Code + PKCE). Configuração: OIDC_ISSUER, OIDC_CLIENT_ID, PUBLIC_BASE_URL. */
export async function GET() {
  const issuer = process.env.OIDC_ISSUER?.replace(/\/+$/, "");
  const clientId = process.env.OIDC_CLIENT_ID;
  const base = process.env.PUBLIC_BASE_URL?.replace(/\/+$/, "");
  if (authMode() !== "oidc" || !issuer || !clientId || !base) {
    return NextResponse.json({ error: "OIDC não configurado (OIDC_ISSUER, OIDC_CLIENT_ID, PUBLIC_BASE_URL)" }, { status: 503 });
  }
  const disco = await fetch(`${issuer}/.well-known/openid-configuration`, { cache: "no-store" }).catch(() => null);
  if (!disco?.ok) return NextResponse.json({ error: "provedor de identidade indisponível" }, { status: 502 });
  const { authorization_endpoint } = (await disco.json()) as { authorization_endpoint: string };
  const state = randomBytes(16).toString("base64url");
  const nonce = randomBytes(16).toString("base64url");
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  (await cookies()).set(OIDC_COOKIE, JSON.stringify({ state, nonce, verifier }), {
    httpOnly: true, sameSite: "lax", path: "/api/auth/oidc", secure: secureCookies(), maxAge: 600,
  });
  const url = new URL(authorization_endpoint);
  url.search = new URLSearchParams({
    response_type: "code", client_id: clientId, redirect_uri: `${base}/api/auth/oidc/callback`, scope: "openid email profile",
    state, nonce, code_challenge: challenge, code_challenge_method: "S256",
  }).toString();
  return NextResponse.redirect(url);
}
