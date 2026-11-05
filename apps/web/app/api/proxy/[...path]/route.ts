import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { mutationAllowed, safeApiPath } from "@/lib/proxy";
import { apiBase, SESSION_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

async function forward(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const safe = safeApiPath(path);
  if (!safe) return NextResponse.json({ detail: "caminho não permitido" }, { status: 400 });
  const h = req.headers;
  if (!mutationAllowed(req.method, { origin: h.get("origin"), host: h.get("host"), requestedWith: h.get("x-requested-with") })) {
    return NextResponse.json({ detail: "origem não permitida" }, { status: 403 });
  }
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "sem sessão" }, { status: 401 });
  const search = new URL(req.url).search;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const upstream = await fetch(`${apiBase()}/${safe}${search}`, {
    method: req.method, cache: "no-store",
    headers: { Authorization: `Bearer ${token}`, ...(hasBody ? { "Content-Type": "application/json" } : {}) },
    body: hasBody ? await req.text() : undefined,
  }).catch(() => null);
  if (!upstream) return NextResponse.json({ detail: "API indisponível" }, { status: 502 });
  const out = new NextResponse(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status });
  out.headers.set("Content-Type", upstream.headers.get("content-type") ?? "application/json");
  const disp = upstream.headers.get("content-disposition");
  if (disp) out.headers.set("Content-Disposition", disp);
  out.headers.set("Cache-Control", "no-store");
  const total = upstream.headers.get("x-total-count");
  if (total) out.headers.set("X-Total-Count", total);
  return out;
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
