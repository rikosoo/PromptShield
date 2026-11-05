import { NextResponse } from "next/server";
import { authMode } from "@/lib/session";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ mode: authMode() });
}
