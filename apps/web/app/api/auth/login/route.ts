import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiBase, authMode, cookieMaxAge, SESSION_COOKIE, secureCookies } from "@/lib/session";
import { mutationAllowed } from "@/lib/proxy";

/**
 * Login do console. AUTH_MODE=local: e-mail e senha conferidos pela API (sessão assinada, cookie httpOnly).
 * AUTH_MODE=mock: DESENVOLVIMENTO, troca só o e-mail por um token simulado da API (OIDC_MODE=mock).
 */
export async function POST(req: Request) {
  if (authMode() !== "mock" && authMode() !== "local") return NextResponse.json({ error: "login por e-mail desligado" }, { status: 404 });
  const h = req.headers;
  if (!mutationAllowed("POST", { origin: h.get("origin"), host: h.get("host"), requestedWith: h.get("x-requested-with") })) {
    return NextResponse.json({ error: "origem não permitida" }, { status: 403 });
  }
  const { email, password } = (await req.json().catch(() => ({}))) as { email?: string; password?: string };
  if (!email) return NextResponse.json({ error: "informe o e-mail" }, { status: 400 });
  if (authMode() === "local") {
    if (!password) return NextResponse.json({ error: "informe a senha" }, { status: 400 });
    const r = await fetch(`${apiBase()}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }), cache: "no-store" }).catch(() => null);
    if (!r) return NextResponse.json({ error: "servidor indisponível" }, { status: 502 });
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      return NextResponse.json({ error: typeof j.detail === "string" ? j.detail : "não foi possível entrar" }, { status: r.status === 429 ? 429 : 401 });
    }
    const t = (await r.json()) as { access_token: string; must_change_password: boolean };
    (await cookies()).set(SESSION_COOKIE, t.access_token, { httpOnly: true, sameSite: "lax", path: "/", secure: secureCookies(), maxAge: cookieMaxAge(t.access_token) });
    return NextResponse.json({ ok: true, must_change_password: t.must_change_password });
  }
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
