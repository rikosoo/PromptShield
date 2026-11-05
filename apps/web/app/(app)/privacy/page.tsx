"use client";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { ApiKeyRow, DataMap, Tenant } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

interface Subject { subject: string; events: unknown[]; incidents: number; alerts: number; truncated: boolean }

export default function PrivacyPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const canAudit = isAdmin || me.role === "auditor";
  const { groups } = useTaxonomy();
  const map = useLoad(() => api<DataMap>("v1/privacy/data-map"), []);
  const tenant = useLoad(() => api<Tenant>("v1/tenant"), []);
  const keys = useLoad(() => (isAdmin ? api<ApiKeyRow[]>("v1/api-keys") : Promise.resolve([] as ApiKeyRow[])), [isAdmin]);
  const [retention, setRetention] = useState("");
  const [original, setOriginal] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [subjectId, setSubjectId] = useState("");
  const [subject, setSubject] = useState<Subject | null>(null);
  const [justification, setJustification] = useState("");
  const [newKey, setNewKey] = useState<{ key: string; name: string } | null>(null);
  const [keyName, setKeyName] = useState("");
  const [grace, setGrace] = useState(24);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { const extra = await fn(); setMsg({ ok: true, text: typeof extra === "string" && extra ? extra : ok }); map.reload(); tenant.reload(); keys.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro" }); } finally { setBusy(false); }
  }
  const saveRetention = (ev: FormEvent) => { ev.preventDefault(); void run(() => send("PATCH", "v1/tenant", { ...(retention ? { retention_days: Number(retention) } : {}), ...(original ? { original_retention_days: Number(original) } : {}) }), "Retenção salva."); };
  const toggleOmit = (id: string, on: boolean) => run(() => send("PATCH", "v1/tenant", { omit_text_categories: on ? [...(tenant.data?.omit_text_categories ?? []), id] : (tenant.data?.omit_text_categories ?? []).filter((c) => c !== id) }), "Categorias sem guarda de texto atualizadas.");
  const toggleOriginal = (on: boolean) => run(() => send("PATCH", "v1/tenant", { store_original: on }), on ? "Guarda do texto original LIGADA (cifrado, com prazo próprio)." : "Guarda do texto original desligada.");
  const runRetention = () => { if (confirm("Apagar agora tudo o que passou do prazo de retenção? Não dá para desfazer.")) void run(async () => { const c = await send<Record<string, number>>("POST", "v1/privacy/retention/run"); return `Retenção executada: ${c.events} evento(s) e ${c.originals_erased} texto(s) original(is) apagados.`; }, ""); };
  const lookup = async () => { setMsg(null); try { setSubject(await api<Subject>(`v1/privacy/subject?user_id=${encodeURIComponent(subjectId)}`)); } catch (e) { setSubject(null); setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro" }); } };
  const erase = () => { if (confirm(`Eliminar TODOS os dados de "${subjectId}"? Não dá para desfazer.`)) void run(async () => { const r = await send<{ events_deleted: number; incidents_deleted: number; alerts_deleted: number; reports_to_review: number }>("POST", "v1/privacy/subject/erase", { user_id: subjectId, justification }); setSubject(null); return `Eliminado: ${r.events_deleted} evento(s), ${r.incidents_deleted} incidente(s), ${r.alerts_deleted} alerta(s). Revise ${r.reports_to_review} relatório(s) gerado(s) que podem citar a pessoa.`; }, ""); };
  const rotate = (k: ApiKeyRow) => run(async () => { const r = await send<{ key: string; name: string }>("POST", `v1/api-keys/${k.id}/rotate`, { grace_hours: grace }); setNewKey({ key: r.key, name: r.name }); }, "Chave rotacionada.");
  const revoke = (k: ApiKeyRow) => { if (confirm(`Revogar a chave ${k.prefix}? Quem a usa deixa de enviar eventos.`)) void run(() => send("POST", `v1/api-keys/${k.id}/revoke`), "Chave revogada."); };
  const createKey = (ev: FormEvent) => { ev.preventDefault(); void run(async () => { const r = await send<{ key: string; name: string }>("POST", "v1/api-keys", { name: keyName }); setNewKey({ key: r.key, name: r.name }); setKeyName(""); }, "Chave criada."); };

  const m = map.data, t = tenant.data;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Privacidade e segurança</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">Mapa dos dados que o produto guarda, retenção, direitos do titular e chaves de API. Modelo de documentos de LGPD, GDPR e EUA em docs/lgpd.md (precisa de revisão de um advogado).</p>
      </div>
      {map.error && <ErrorBox message={map.error} onRetry={map.reload} />}
      {map.loading && !m && <Loading />}
      {m && (
        <Panel title="Mapa de dados deste tenant">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Dados guardados">
            <Kpi label="Eventos guardados" value={m.counts.events} hint="texto sempre mascarado" />
            <Kpi label="Pessoas monitoradas" value={m.counts.distinct_monitored_people} />
            <Kpi label="Com texto original cifrado" value={m.counts.events_with_original} hint={m.original_text_stored ? `apagado após ${m.original_retention_days} dias` : "guarda desligada"} />
            <Kpi label="Retenção" value={`${m.retention_days} dias`} hint={m.last_retention_run ? `última execução ${whenFull(m.last_retention_run)}` : "ainda não executada"} />
          </div>
          <p className="mt-3 text-xs text-muted">Evento mais antigo: {m.counts.oldest_event_received_at ? whenFull(m.counts.oldest_event_received_at) : "nenhum"}. Registro de auditoria: {m.audit_log}.</p>
        </Panel>
      )}

      <Panel title="Retenção">
        {!isAdmin && <p className="text-sm text-muted">Só o administrador altera a retenção.</p>}
        {isAdmin && t && (
          <div className="space-y-3 text-sm">
            <form onSubmit={saveRetention} className="flex flex-wrap items-end gap-3">
              <div><label htmlFor="ret" className="mb-1 block font-medium">Guardar eventos por (dias)</label><input id="ret" type="number" min={7} max={365} className="field w-32" value={retention} placeholder={String(t.retention_days)} onChange={(e) => setRetention(e.target.value)} /></div>
              <div><label htmlFor="oret" className="mb-1 block font-medium">Guardar texto original por (dias)</label><input id="oret" type="number" min={1} max={365} className="field w-32" value={original} placeholder={String(t.original_retention_days)} onChange={(e) => setOriginal(e.target.value)} /></div>
              <button className="btn" disabled={busy}>Salvar prazos</button>
              <button type="button" className="btn" disabled={busy} onClick={runRetention}>Executar retenção agora</button>
            </form>
            <label className="flex items-center gap-2"><input type="checkbox" checked={t.store_original} disabled={busy} onChange={(e) => toggleOriginal(e.target.checked)} /> Guardar também o texto <strong>original</strong> (cifrado). Desligado por padrão: o padrão é guardar só o texto mascarado.</label>
            <details className="rounded border border-line p-3" data-testid="omit-categories">
              <summary className="cursor-pointer font-medium">Categorias cujo texto <strong>não é guardado</strong> ({t.omit_text_categories.length} marcada{t.omit_text_categories.length === 1 ? "" : "s"})</summary>
              <p className="mt-2 text-xs text-muted">O mascaramento cobre identificadores estruturados (CPF, cartões, chaves...). Texto livre sensível, como saúde, só é protegido se a categoria estiver marcada aqui: o evento guarda um aviso no lugar do texto e continua classificado e pontuado. Saúde vem marcada por padrão.</p>
              <div className="mt-2 grid max-h-56 gap-3 overflow-y-auto sm:grid-cols-2">
                {groups.map((g) => (
                  <fieldset key={g.group}><legend className="text-xs font-semibold text-muted">{g.group}</legend>
                    {g.items.map((c) => <label key={c.id} className="flex items-center gap-2 py-0.5"><input type="checkbox" checked={t.omit_text_categories.includes(c.id)} disabled={busy} onChange={(e) => toggleOmit(c.id, e.target.checked)} /> {c.nome}</label>)}
                  </fieldset>
                ))}
              </div>
            </details>
            <p className="text-xs text-muted">O texto original sempre vence antes dos demais dados (nunca depois). O worker executa a retenção uma vez por dia.</p>
          </div>
        )}
      </Panel>

      <Panel title="Direitos do titular (pessoa monitorada)">
        {!canAudit ? <p className="text-sm text-muted">Só administrador e auditor consultam; só o administrador elimina.</p> : (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[16rem] flex-1"><label htmlFor="subj" className="mb-1 block font-medium">Identificador da pessoa (como aparece nos eventos)</label><input id="subj" className="field w-full" value={subjectId} onChange={(e) => setSubjectId(e.target.value)} /></div>
              <button type="button" className="btn" disabled={!subjectId || busy} onClick={lookup}>Consultar o que guardamos</button>
            </div>
            {subject && (
              <div role="region" aria-label="Resultado da consulta" data-testid="subject-result" className="rounded border border-line bg-panel2 p-3">
                <p><strong data-testid="subject-events">{subject.events.length}</strong> evento(s), {subject.incidents} incidente(s), {subject.alerts} alerta(s){subject.truncated ? " (lista truncada)" : ""}. O texto aparece só mascarado; o original nunca sai por esta tela.</p>
                {isAdmin && (
                  <div className="mt-3 space-y-2">
                    <label htmlFor="just" className="block font-medium">Justificativa da eliminação (mínimo 10 caracteres; fica na auditoria)</label>
                    <textarea id="just" className="field w-full" rows={2} value={justification} onChange={(e) => setJustification(e.target.value)} />
                    <button type="button" className="btn-primary" disabled={busy || justification.trim().length < 10} onClick={erase}>Eliminar os dados desta pessoa</button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Chaves de API" action={isAdmin ? undefined : undefined}>
        {!isAdmin && <p className="text-sm text-muted">Só o administrador gerencia chaves.</p>}
        {isAdmin && (
          <>
            <form onSubmit={createKey} className="mb-3 flex flex-wrap items-end gap-3 text-sm">
              <div><label htmlFor="kname" className="mb-1 block font-medium">Nova chave (nome)</label><input id="kname" required className="field" value={keyName} onChange={(e) => setKeyName(e.target.value)} /></div>
              <button className="btn" disabled={busy}>Criar chave</button>
              <div className="ml-auto"><label htmlFor="grace" className="mr-2">Ao rotacionar, a antiga vale por</label>
                <select id="grace" className="field" value={grace} onChange={(e) => setGrace(Number(e.target.value))}>{[0, 1, 24, 72, 168].map((h) => <option key={h} value={h}>{h === 0 ? "0 h (revoga já)" : `${h} h`}</option>)}</select></div>
            </form>
            {keys.data && (keys.data.length === 0 ? <Empty>Nenhuma chave.</Empty> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[40rem] border-collapse" data-testid="keys-table">
                <caption className="sr-only">Chaves de API</caption>
                <thead><tr><th scope="col" className="th">Nome</th><th scope="col" className="th">Prefixo</th><th scope="col" className="th">Situação</th><th scope="col" className="th">Expira</th><th scope="col" className="th">Último uso</th><th scope="col" className="th"><span className="sr-only">Ações</span></th></tr></thead>
                <tbody>{keys.data.map((k) => (
                  <tr key={k.id} data-testid="key-row">
                    <th scope="row" className="td text-left font-medium">{k.name}</th><td className="td font-mono text-xs">{k.prefix}</td><td className="td">{k.status}</td>
                    <td className="td text-xs">{k.expires_at ? whenFull(k.expires_at) : "—"}</td><td className="td text-xs">{k.last_used_at ? whenFull(k.last_used_at) : "nunca"}</td>
                    <td className="td">{!k.revoked && <div className="flex gap-2"><button type="button" className="btn" disabled={busy} onClick={() => rotate(k)}>Rotacionar</button><button type="button" className="btn" disabled={busy} onClick={() => revoke(k)}>Revogar</button></div>}</td>
                  </tr>))}</tbody>
              </table></div>
            ))}
          </>
        )}
      </Panel>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "" : "text-crit"}`}>{msg.text}</p>}
      <Dialog open={!!newKey} onClose={() => setNewKey(null)} title="Chave de API criada">
        {newKey && <div className="space-y-3 text-sm"><p>Copie agora: <strong>esta é a única vez</strong> que a chave aparece.</p><code className="block break-all rounded border border-line bg-panel2 p-2 font-mono text-xs" data-testid="new-key">{newKey.key}</code><div className="flex justify-end"><button type="button" className="btn-primary" onClick={() => setNewKey(null)}>Já guardei</button></div></div>}
      </Dialog>
    </div>
  );
}
