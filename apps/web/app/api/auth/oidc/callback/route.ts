import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { cookieMaxAge, OIDC_COOKIE, SESSION_COOKIE, secureCookies } from "@/lib/session";

function fail(base: string, why: string) {
  return NextResponse.redirect(`${base}/login?erro=${encodeURIComponent(why)}`);
}

/** Fim do login OIDC: troca o código pelo id_token no servidor e guarda só em cookie httpOnly. A API valida o token. */
export async function GET(req: Request) {
  const issuer = process.env.OIDC_ISSUER?.replace(/\/+$/, "");
  const clientId = process.env.OIDC_CLIENT_ID;
  const base = (process.env.PUBLIC_BASE_URL ?? "").replace(/\/+$/, "");
  if (!issuer || !clientId || !base) return NextResponse.json({ error: "OIDC não configurado" }, { status: 503 });
  const jar = await cookies();
  const saved = jar.get(OIDC_COOKIE)?.value;
  jar.delete(OIDC_COOKIE);
  const q = new URL(req.url).searchParams;
  if (q.get("error")) return fail(base, "o provedor recusou o login");
  let ctx: { state: string; nonce: string; verifier: string };
  try { ctx = JSON.parse(saved ?? ""); } catch { return fail(base, "sessão de login expirada"); }
  if (!q.get("code") || q.get("state") !== ctx.state) return fail(base, "estado de login inválido");
  const disco = await fetch(`${issuer}/.well-known/openid-configuration`, { cache: "no-store" }).catch(() => null);
  if (!disco?.ok) return fail(base, "provedor indisponível");
  const { token_endpoint } = (await disco.json()) as { token_endpoint: string };
  const form = new URLSearchParams({
    grant_type: "authorization_code", code: q.get("code")!, redirect_uri: `${base}/api/auth/oidc/callback`,
    client_id: clientId, code_verifier: ctx.verifier,
  });
  if (process.env.OIDC_CLIENT_SECRET) form.set("client_secret", process.env.OIDC_CLIENT_SECRET);
  const tr = await fetch(token_endpoint, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form, cache: "no-store" }).catch(() => null);
  if (!tr?.ok) return fail(base, "não foi possível concluir o login");
  const { id_token } = (await tr.json()) as { id_token?: string };
  if (!id_token) return fail(base, "o provedor não devolveu id_token");
  const payload = JSON.parse(Buffer.from(id_token.split(".")[1], "base64url").toString("utf8")) as { nonce?: string };
  if (payload.nonce !== ctx.nonce) return fail(base, "nonce inválido");
  jar.set(SESSION_COOKIE, id_token, { httpOnly: true, sameSite: "lax", path: "/", secure: secureCookies(), maxAge: cookieMaxAge(id_token) });
  return NextResponse.redirect(`${base}/`);
}
