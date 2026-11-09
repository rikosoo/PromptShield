import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { mutationAllowed } from "@/lib/proxy";
import { apiBase, cookieMaxAge, SESSION_COOKIE, secureCookies } from "@/lib/session";

/** Troca da PRÓPRIA senha. A API devolve uma sessão nova (a antiga deixa de valer); aqui ela vira o cookie. */
export async function POST(req: Request) {
  const h = req.headers;
  if (!mutationAllowed("POST", { origin: h.get("origin"), host: h.get("host"), requestedWith: h.get("x-requested-with") })) {
    return NextResponse.json({ error: "origem não permitida" }, { status: 403 });
  }
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "sem sessão" }, { status: 401 });
  const body = (await req.json().catch(() => ({}))) as { current_password?: string; new_password?: string };
  const r = await fetch(`${apiBase()}/v1/me/password`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ current_password: body.current_password ?? "", new_password: body.new_password ?? "" }),
  }).catch(() => null);
  if (!r) return NextResponse.json({ error: "servidor indisponível" }, { status: 502 });
  const j = (await r.json().catch(() => ({}))) as { access_token?: string; detail?: string };
  if (!r.ok || !j.access_token) return NextResponse.json({ error: typeof j.detail === "string" ? j.detail : "não foi possível trocar a senha" }, { status: r.status === 401 ? 401 : r.status });
  jar.set(SESSION_COOKIE, j.access_token, { httpOnly: true, sameSite: "lax", path: "/", secure: secureCookies(), maxAge: cookieMaxAge(j.access_token) });
  return NextResponse.json({ ok: true });
}
