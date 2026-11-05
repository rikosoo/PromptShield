import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiBase, authMode, cookieMaxAge, SESSION_COOKIE, secureCookies } from "@/lib/session";
import { mutationAllowed } from "@/lib/proxy";

/** Login de DESENVOLVIMENTO (AUTH_MODE=mock): troca o e-mail por um token simulado da API (OIDC_MODE=mock). */
export async function POST(req: Request) {
  if (authMode() !== "mock") return NextResponse.json({ error: "login simulado desligado" }, { status: 404 });
  const h = req.headers;
  if (!mutationAllowed("POST", { origin: h.get("origin"), host: h.get("host"), requestedWith: h.get("x-requested-with") })) {
    return NextResponse.json({ error: "origem não permitida" }, { status: 403 });
  }
  const { email } = (await req.json().catch(() => ({}))) as { email?: string };
  if (!email) return NextResponse.json({ error: "informe o e-mail" }, { status: 400 });
  const r = await fetch(`${apiBase()}/dev/token`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }), cache: "no-store" }).catch(() => null);
  if (!r?.ok) return NextResponse.json({ error: "não foi possível entrar" }, { status: r ? 401 : 502 });
  const { access_token } = (await r.json()) as { access_token: string };
  // confere se o usuário existe de verdade antes de aceitar a sessão
  const me = await fetch(`${apiBase()}/v1/me`, { headers: { Authorization: `Bearer ${access_token}` }, cache: "no-store" }).catch(() => null);
  if (!me?.ok) return NextResponse.json({ error: "usuário não cadastrado ou inativo" }, { status: 401 });
  (await cookies()).set(SESSION_COOKIE, access_token, {
    httpOnly: true, sameSite: "lax", path: "/", secure: secureCookies(), maxAge: cookieMaxAge(access_token),
  });
  return NextResponse.json({ ok: true });
}
