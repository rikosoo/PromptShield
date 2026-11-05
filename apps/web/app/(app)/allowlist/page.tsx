"use client";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { AllowlistRow } from "@/lib/types";

export default function AllowlistPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const rows = useLoad(() => api<AllowlistRow[]>("v1/allowlist"), []);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); rows.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }
  const add = (ev: FormEvent) => { ev.preventDefault(); void run(async () => { await send("POST", "v1/allowlist", { kind: "host", value, note: note.trim() || null }); setValue(""); setNote(""); }, "Domínio permitido. Vale para os próximos eventos."); };
  const remove = (r: AllowlistRow) => { if (confirm(`Tirar ${r.value} da lista?`)) void run(() => send("DELETE", `v1/allowlist/${r.id}`), "Domínio removido."); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Domínios permitidos</h1>
        <p className="text-sm text-muted">Destinos que a empresa aprovou (por exemplo, a API de um parceiro). Comandos de agente que acessam esses domínios, <strong>e seus subdomínios</strong>, não geram alerta de rede externa nem de instalação de pacote de origem não padrão.</p>
      </div>
      <p role="note" className="rounded border border-med bg-med-bg px-3 py-2 text-sm text-med">
        <strong>Cuidado:</strong> por ser um destino aprovado, o <strong>envio de dados</strong> para esse domínio também deixa de ser sinalizado como exfiltração. Permita só domínios que a empresa controla ou contratou. Segredos e dados pessoais continuam sendo detectados e mascarados normalmente: esta lista não os afeta.
      </p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>{msg.text}</p>}
      {isAdmin && (
        <Panel title="Permitir um domínio">
          <form onSubmit={add} className="grid gap-3 md:grid-cols-2" aria-label="Permitir um domínio">
            <div><label htmlFor="ahost" className="block text-xs text-muted">Domínio (sem http://, caminho ou curinga)</label><input id="ahost" className="field w-full font-mono" required maxLength={253} placeholder="api.parceiro.com.br" value={value} onChange={(e) => setValue(e.target.value)} /></div>
            <div><label htmlFor="anote" className="block text-xs text-muted">Por que (opcional)</label><input id="anote" className="field w-full" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></div>
            <div><button type="submit" className="btn-primary" disabled={busy || !value.trim()}>Permitir</button></div>
          </form>
        </Panel>
      )}
      <Panel title="Lista">
        {rows.error && <ErrorBox message={rows.error} onRetry={rows.reload} />}
        {rows.loading && !rows.data && <Loading />}
        {rows.data && rows.data.length === 0 && <Empty>Nenhum domínio permitido. Só os padrões do sistema (registros de pacotes e repositórios conhecidos) valem.</Empty>}
        {rows.data && rows.data.length > 0 && (
          <table className="w-full text-sm" data-testid="allowlist-table">
            <thead><tr className="text-left text-xs text-muted"><th className="py-1">Domínio</th><th>Motivo</th><th>Desde</th><th /></tr></thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="py-1 font-mono">{r.value}</td><td>{r.note}</td><td>{whenFull(r.created_at)}</td>
                  <td className="text-right">{isAdmin && <button type="button" className="btn" disabled={busy} onClick={() => remove(r)} aria-label={`Tirar ${r.value} da lista`}>Tirar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
