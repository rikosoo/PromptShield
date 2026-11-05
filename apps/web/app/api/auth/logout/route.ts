import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";
import { mutationAllowed } from "@/lib/proxy";

export async function POST(req: Request) {
  const h = req.headers;
  if (!mutationAllowed("POST", { origin: h.get("origin"), host: h.get("host"), requestedWith: h.get("x-requested-with") })) {
    return NextResponse.json({ error: "origem não permitida" }, { status: 403 });
  }
  (await cookies()).delete(SESSION_COOKIE);
  return NextResponse.json({ ok: true });
}
