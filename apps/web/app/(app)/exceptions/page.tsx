"use client";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { PolicyExceptionRow, Policy, UserGroup } from "@/lib/types";

const DAYS = [1, 7, 30, 90, 180, 365];
const STATE_CLASS = { vigente: "border-med bg-med-bg text-med", vencida: "border-line text-muted", revogada: "border-line text-muted" } as const;

export default function ExceptionsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const [onlyActive, setOnlyActive] = useState(true);
  const rows = useLoad(() => api<PolicyExceptionRow[]>(`v1/exceptions?only_active=${onlyActive}`), [onlyActive]);
  const policies = useLoad(() => api<Policy[]>("v1/policies"), []);
  const groups = useLoad(() => api<UserGroup[]>("v1/groups"), []);
  const [policyId, setPolicyId] = useState("");
  const [target, setTarget] = useState<"user" | "group">("user");
  const [who, setWho] = useState("");
  const [reason, setReason] = useState("");
  const [days, setDays] = useState(7);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); rows.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }
  const create = (ev: FormEvent) => {
    ev.preventDefault();
    const expires_at = new Date(Date.now() + days * 86_400_000).toISOString();
    void run(async () => { await send("POST", `v1/policies/${policyId}/exceptions`, { [target === "user" ? "user_id" : "group"]: who.trim(), reason: reason.trim(), expires_at }); setWho(""); setReason(""); }, "Exceção criada. Vale já para os próximos eventos.");
  };
  const revoke = (x: PolicyExceptionRow) => { if (confirm(`Revogar a exceção de ${x.user_id ?? x.group} em «${x.policy_name}»?`)) void run(() => send("POST", `v1/exceptions/${x.id}/revoke`), "Exceção revogada."); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Exceções de política</h1>
        <p className="text-sm text-muted">A política deixa de valer para uma pessoa ou grupo, <strong>com motivo e validade obrigatórios</strong> (máximo de 365 dias). O evento continua sendo analisado, gravado e aparece com o selo «exceção»; só a decisão da política não é aplicada. Toda criação e revogação fica na auditoria.</p>
      </div>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>{msg.text}</p>}
      {isAdmin && (
        <Panel title="Nova exceção">
          <form onSubmit={create} className="grid gap-3 md:grid-cols-2" aria-label="Nova exceção">
            <div><label htmlFor="xpol" className="block text-xs text-muted">Política</label>
              <select id="xpol" className="field w-full" required value={policyId} onChange={(e) => setPolicyId(e.target.value)}>
                <option value="">Escolha…</option>
                {(policies.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select></div>
            <fieldset className="text-sm"><legend className="block text-xs text-muted">Vale para</legend>
              <label className="mr-4"><input type="radio" name="target" checked={target === "user"} onChange={() => { setTarget("user"); setWho(""); }} /> uma pessoa</label>
              <label><input type="radio" name="target" checked={target === "group"} onChange={() => { setTarget("group"); setWho(""); }} /> um grupo</label></fieldset>
            <div>
              {target === "user"
                ? <><label htmlFor="xwho" className="block text-xs text-muted">Identificador da pessoa</label><input id="xwho" className="field w-full font-mono" required maxLength={200} value={who} onChange={(e) => setWho(e.target.value)} /></>
                : <><label htmlFor="xgrp" className="block text-xs text-muted">Grupo</label>
                  <select id="xgrp" className="field w-full" required value={who} onChange={(e) => setWho(e.target.value)}>
                    <option value="">Escolha…</option>
                    {(groups.data ?? []).map((g) => <option key={g.id} value={g.name}>{g.name}</option>)}
                  </select></>}
            </div>
            <div><label htmlFor="xdays" className="block text-xs text-muted">Validade</label>
              <select id="xdays" className="field w-full" value={days} onChange={(e) => setDays(Number(e.target.value))}>{DAYS.map((d) => <option key={d} value={d}>{d} dia{d > 1 ? "s" : ""}</option>)}</select></div>
            <div className="md:col-span-2"><label htmlFor="xreason" className="block text-xs text-muted">Motivo (mínimo de 10 caracteres; não escreva dado pessoal)</label>
              <input id="xreason" className="field w-full" required minLength={10} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></div>
            <div><button type="submit" className="btn-primary" disabled={busy || !policyId || !who.trim() || reason.trim().length < 10}>Criar exceção</button></div>
          </form>
        </Panel>
      )}
      <Panel title="Exceções" action={<label className="text-sm"><input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} /> só as vigentes</label>}>
        {rows.error && <ErrorBox message={rows.error} onRetry={rows.reload} />}
        {rows.loading && !rows.data && <Loading />}
        {rows.data && rows.data.length === 0 && <Empty>Nenhuma exceção{onlyActive ? " vigente" : ""}.</Empty>}
        {rows.data && rows.data.length > 0 && (
          <div className="relative overflow-x-auto"><table className="w-full text-sm" data-testid="exceptions-table">
            <thead><tr className="text-left text-xs text-muted"><th className="py-1">Política</th><th>Para</th><th>Motivo</th><th>Vence</th><th>Situação</th><th /></tr></thead>
            <tbody>
              {rows.data.map((x) => (
                <tr key={x.id} className="border-t border-line align-top">
                  <td className="py-1">{x.policy_name}</td>
                  <td>{x.user_id ? <span className="font-mono">{x.user_id}</span> : <span>grupo <strong>{x.group}</strong></span>}</td>
                  <td className="max-w-xs">{x.reason}</td>
                  <td>{whenFull(x.expires_at)}</td>
                  <td><span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${STATE_CLASS[x.state]}`}>{x.state}</span></td>
                  <td className="text-right">{isAdmin && x.state === "vigente" && <button type="button" className="btn" disabled={busy} onClick={() => revoke(x)}>Revogar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </Panel>
    </div>
  );
}
