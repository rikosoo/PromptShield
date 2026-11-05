"use client";
import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface Page<T> { items: T; total: number }

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(`/api/proxy/${path.replace(/^\//, "")}`, {
    ...init,
    headers: { "X-Requested-With": "promptshield", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (r.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
    location.assign("/login");
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : typeof body.detail?.message === "string" ? body.detail.message : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : `Erro ${r.status}`;
    throw new ApiError(r.status, detail);
  }
  return r;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await request(path, init);
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}

export async function apiPage<T>(path: string): Promise<Page<T>> {
  const r = await request(path);
  return { items: (await r.json()) as T, total: Number(r.headers.get("x-total-count") ?? "0") };
}

export const send = <T,>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown) =>
  api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    run().then(
      (data) => alive && setState({ data, loading: false }),
      (e: unknown) => alive && setState({ error: e instanceof Error ? e.message : String(e), loading: false }),
    );
    return () => { alive = false; };
  }, [run, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "" && v !== false) u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};
