"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel, SeverityBadge } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { when } from "@/lib/format";
import { CHANNEL_LABEL, CHANNEL_STATUS_LABEL, CHANNEL_TARGET_HINT, SEVERITY_LABEL } from "@/lib/labels";
import type { AlertRow, Channel, ChannelKind, Severity } from "@/lib/types";

const RULES = [["severidade", "Evento de risco alto ou crítico"], ["injection", "Injection com confiança alta"], ["volume", "Volume anormal"], ["agente", "Agente fora do padrão"]];
const ALERT_KINDS: ChannelKind[] = ["webhook", "slack", "teams", "email"];

interface Draft { kind: ChannelKind; name: string; target: string; min_severity: Severity; min_score: number; proto: "udp" | "tcp"; secret: string }
const blank = (): Draft => ({ kind: "webhook", name: "", target: "", min_severity: "medio", min_score: 35, proto: "udp", secret: "" });

export default function AlertsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const [rule, setRule] = useState("");
  const alerts = useLoad(() => api<AlertRow[]>(`v1/alerts${rule ? `?rule=${rule}` : ""}`), [rule]);
  const channels = useLoad(() => (isAdmin ? api<Channel[]>("v1/channels") : Promise.resolve([] as Channel[])), [isAdmin]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const set = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));

  async function create(ev: FormEvent) {
    ev.preventDefault();
    if (!draft) return;
    setBusy(true);
    setFormErr(null);
    const isAlert = ALERT_KINDS.includes(draft.kind);
    try {
      await send("POST", "v1/channels", {
        kind: draft.kind, name: draft.name, target: draft.target,
        ...(isAlert ? { min_severity: draft.min_severity } : { min_score: draft.min_score }),
        ...(draft.kind === "syslog_cef" ? { proto: draft.proto } : {}),
        ...(draft.secret ? { secret: draft.secret } : {}),
      });
      setDraft(null);
      channels.reload();
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : "Erro ao criar");
    } finally {
      setBusy(false);
    }
  }
  async function test(c: Channel) {
    setTestResult((r) => ({ ...r, [c.id]: "Enviando…" }));
    try {
      const r = await send<{ ok: boolean; error: string | null }>("POST", `v1/channels/${c.id}/test`);
      setTestResult((x) => ({ ...x, [c.id]: r.ok ? "Teste enviado com sucesso." : `Falhou: ${r.error}` }));
      channels.reload();
    } catch (e) {
      setTestResult((x) => ({ ...x, [c.id]: e instanceof Error ? e.message : "Erro" }));
    }
  }
  async function toggle(c: Channel) { await send("PATCH", `v1/channels/${c.id}`, { enabled: !c.enabled }); channels.reload(); }
  async function remove(c: Channel) {
    if (!confirm(`Remover o canal "${c.name}"?`)) return;
    await send("DELETE", `v1/channels/${c.id}`);
    channels.reload();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Alertas e exportação para SIEM</h1>
      <Panel title="Alertas" action={
        <span><label htmlFor="rule" className="mr-2 text-sm text-muted">Regra</label>
          <select id="rule" className="field" value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value="">Todas</option>{RULES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></span>}>
        <p className="mb-3 text-xs text-muted">Um alerta por regra, usuário, categoria e janela de tempo: ocorrências repetidas aumentam o contador em vez de gerar nova notificação. Indicador de risco, requer revisão humana.</p>
        {alerts.error && <ErrorBox message={alerts.error} onRetry={alerts.reload} />}
        {alerts.loading && !alerts.data && <Loading />}
        {alerts.data && (alerts.data.length === 0 ? <Empty>Nenhum alerta no período.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] border-collapse" data-testid="alerts-table">
              <caption className="sr-only">Alertas</caption>
              <thead><tr><th scope="col" className="th">Severidade</th><th scope="col" className="th">Alerta</th><th scope="col" className="th">Usuário</th><th scope="col" className="th">Ocorrências</th><th scope="col" className="th">Última</th><th scope="col" className="th"><span className="sr-only">Incidente</span></th></tr></thead>
              <tbody>{alerts.data.map((a) => (
                <tr key={a.id} data-testid="alert-row">
                  <td className="td"><SeverityBadge severity={a.severity} /></td>
                  <th scope="row" className="td text-left font-medium">{a.title}<div className="text-xs font-normal text-muted">{a.rule_label}</div></th>
                  <td className="td font-mono text-xs">{a.user_id}{a.department ? ` (${a.department})` : ""}</td>
                  <td className="td font-mono">{a.count}</td>
                  <td className="td text-xs">{when(a.last_seen)}</td>
                  <td className="td">{a.incident_id && <Link className="text-accent underline" href={`/incidents/${a.incident_id}`}>Abrir incidente</Link>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        ))}
      </Panel>

      <Panel title="Canais de notificação e SIEM" action={isAdmin ? <button type="button" className="btn-primary" onClick={() => { setFormErr(null); setDraft(blank()); }}>Novo canal</button> : undefined}>
        {!isAdmin && <p className="text-sm text-muted">Só o administrador configura canais.</p>}
        {isAdmin && channels.error && <ErrorBox message={channels.error} onRetry={channels.reload} />}
        {isAdmin && channels.data && (channels.data.length === 0 ? <Empty>Nenhum canal. Sem canais, alertas ficam só no console.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] border-collapse" data-testid="channels-table">
              <caption className="sr-only">Canais</caption>
              <thead><tr><th scope="col" className="th">Canal</th><th scope="col" className="th">Destino</th><th scope="col" className="th">Filtro</th><th scope="col" className="th">Fila</th><th scope="col" className="th"><span className="sr-only">Ações</span></th></tr></thead>
              <tbody>{channels.data.map((c) => (
                <tr key={c.id} data-testid="channel-row">
                  <th scope="row" className="td text-left font-medium">{c.name}{!c.enabled && <span className="ml-2 text-xs text-muted">(desligado)</span>}
                    <div className="text-xs font-normal text-muted">{CHANNEL_LABEL[c.kind]} · <span className="font-mono font-semibold">{CHANNEL_STATUS_LABEL[c.integration_status]}</span></div></th>
                  <td className="td font-mono text-xs">{c.target}</td>
                  <td className="td text-xs">{c.min_severity ? `severidade ≥ ${SEVERITY_LABEL[c.min_severity]}` : c.min_score !== null ? `risco ≥ ${c.min_score}` : "—"}{c.proto ? ` · ${c.proto.toUpperCase()}` : ""}{c.has_secret ? " · assinado" : ""}</td>
                  <td className="td text-xs font-mono">{Object.entries(c.outbox).map(([k, v]) => `${k}: ${v}`).join(", ") || "vazia"}</td>
                  <td className="td"><div className="flex flex-wrap gap-2">
                    <button type="button" className="btn" onClick={() => test(c)}>Testar</button>
                    <button type="button" className="btn" onClick={() => toggle(c)}>{c.enabled ? "Desligar" : "Ligar"}</button>
                    <button type="button" className="btn" onClick={() => remove(c)}>Remover</button></div>
                    {testResult[c.id] && <p role="status" className="mt-1 text-xs">{testResult[c.id]}</p>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        ))}
        <p className="mt-3 text-xs text-muted">Mensagens nunca levam o texto do prompt, só metadados. Exportação por consulta (auditor e administrador): <code>GET /v1/export/cef</code> e <code>/v1/export/events.jsonl</code>. Mapeamento de campos em docs/siem.md.</p>
      </Panel>

      <Dialog open={!!draft} onClose={() => setDraft(null)} title="Novo canal">
        {draft && (
          <form onSubmit={create} className="space-y-3 text-sm">
            <div><label htmlFor="ckind" className="mb-1 block font-medium">Tipo</label>
              <select id="ckind" className="field w-full" value={draft.kind} onChange={(e) => set({ kind: e.target.value as ChannelKind })}>
                {(Object.keys(CHANNEL_LABEL) as ChannelKind[]).map((k) => <option key={k} value={k}>{CHANNEL_LABEL[k]}</option>)}</select></div>
            {draft.kind === "teams" && <p className="rounded border border-line bg-panel2 p-2 text-xs">Teams é EXPERIMENTAL: o formato do webhook do Workflows está marcado como A VERIFICAR. Use o botão Testar.</p>}
            <div><label htmlFor="cname" className="mb-1 block font-medium">Nome</label><input id="cname" required className="field w-full" value={draft.name} onChange={(e) => set({ name: e.target.value })} /></div>
            <div><label htmlFor="ctarget" className="mb-1 block font-medium">Destino ({CHANNEL_TARGET_HINT[draft.kind]})</label><input id="ctarget" required className="field w-full" value={draft.target} onChange={(e) => set({ target: e.target.value })} /></div>
            {ALERT_KINDS.includes(draft.kind) ? (
              <div><label htmlFor="csev" className="mb-1 block font-medium">Severidade mínima</label>
                <select id="csev" className="field" value={draft.min_severity} onChange={(e) => set({ min_severity: e.target.value as Severity })}>
                  {(Object.keys(SEVERITY_LABEL) as Severity[]).map((s) => <option key={s} value={s}>{SEVERITY_LABEL[s]}</option>)}</select></div>
            ) : (
              <div><label htmlFor="cscore" className="mb-1 block font-medium">Enviar eventos com risco a partir de</label><input id="cscore" type="number" min={0} max={100} className="field" value={draft.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} /></div>
            )}
            {draft.kind === "syslog_cef" && (
              <div><label htmlFor="cproto" className="mb-1 block font-medium">Protocolo</label>
                <select id="cproto" className="field" value={draft.proto} onChange={(e) => set({ proto: e.target.value as "udp" | "tcp" })}><option value="udp">UDP</option><option value="tcp">TCP (uma mensagem por linha)</option></select></div>
            )}
            {(draft.kind === "webhook" || draft.kind === "siem_webhook") && (
              <div><label htmlFor="csecret" className="mb-1 block font-medium">Segredo para assinatura HMAC (opcional, 16+ caracteres)</label><input id="csecret" type="password" autoComplete="off" className="field w-full" value={draft.secret} onChange={(e) => set({ secret: e.target.value })} /></div>
            )}
            {formErr && <p role="alert" className="text-crit">{formErr}</p>}
            <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={() => setDraft(null)}>Cancelar</button><button className="btn-primary" disabled={busy}>Criar canal</button></div>
          </form>
        )}
      </Dialog>
    </div>
  );
}
