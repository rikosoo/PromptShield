"use client";
import { createContext, useContext, type ReactNode } from "react";
import { api, useLoad } from "@/lib/api";
import type { LicenseStatus, Me, Tenant } from "@/lib/types";
import { ErrorBox, Loading } from "./ui";

interface Ctx { me: Me; tenant: Tenant; license?: LicenseStatus }
const SessionCtx = createContext<Ctx | null>(null);

export const useSession = () => {
  const v = useContext(SessionCtx);
  if (!v) throw new Error("fora do SessionProvider");
  return v;
};

export const canTriage = (role: Me["role"]) => role === "admin" || role === "analista";

export function SessionProvider({ children }: { children: (ctx: Ctx) => ReactNode }) {
  const { data, error, loading, reload } = useLoad(async () => {
    const [me, tenant, license] = await Promise.all([api<Me>("v1/me"), api<Tenant>("v1/tenant"),
      api<LicenseStatus>("v1/license/status").catch(() => undefined)]);     // servidor mais antigo, sem a rota: sem faixa de licença
    return { me, tenant, license };
  }, []);
  if (loading) return <div className="p-6"><Loading label="Abrindo sessão…" /></div>;
  if (error || !data) return <div className="p-6"><ErrorBox message={error ?? "Sem sessão"} onRetry={reload} /></div>;
  return <SessionCtx.Provider value={data}>{children(data)}</SessionCtx.Provider>;
}
