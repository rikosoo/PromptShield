"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { canTriage, useSession } from "@/components/session";
import { Chip, Empty, ErrorBox, Loading, MaskedText, Panel, RiskBar, SeverityBadge } from "@/components/ui";
import { api, qs, send, useLoad } from "@/lib/api";
import { clip, pct, when } from "@/lib/format";
import { STATUS_LABEL, STATUSES } from "@/lib/labels";
import type { Incident, IncidentStatus, Severity } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

/** Filtro de status: por padrão só os PENDENTES; os tratados saem da vista mas continuam no registro (escolha "Todos" para vê-los). */
const FILTERS: { value: string; label: string; api: string }[] = [
  { value: "pendentes", label: "Pendentes (abertos e em análise)", api: "aberto,em analise" },
  { value: "todos", label: "Todos", api: "" },
  ...STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s], api: s })),
];

/** Ações rápidas por status atual. */
const ACTIONS: Record<IncidentStatus, { to: IncidentStatus; label: string }[]> = {
  aberto: [{ to: "em analise", label: "Em análise" }, { to: "resolvido", label: "Resolver" }, { to: "falso positivo", label: "Falso positivo" }],
  "em analise": [{ to: "resolvido", label: "Resolver" }, { to: "falso positivo", label: "Falso positivo" }, { to: "aberto", label: "Reabrir" }],
  resolvido: [{ to: "aberto", label: "Reabrir" }],
  "falso positivo": [{ to: "aberto", label: "Reabrir" }],
};

export default function IncidentsPage() {
  const { me } = useSession();
  const triage = canTriage(me.role);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("pendentes");
  const [category, setCategory] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; undo?: { id: string; status: IncidentStatus }[] } | null>(null);
  const { name, items } = useTaxonomy();
  const apiStatus = FILTERS.find((f) => f.value === status)?.api ?? "";
  const { data, error, loading, reload } = useLoad(() => api<Incident[]>(`v1/incidents${qs({ severity, status: apiStatus, category, limit: 100 })}`), [severity, apiStatus, category]);
  useEffect(() => setPicked([]), [severity, apiStatus, category]);

  /** Muda o status de um ou mais incidentes; guarda o status anterior para o "Desfazer". */
  async function change(rows: Incident[], to: IncidentStatus) {
    setBusy(true);
    setMsg(null);
    const before = rows.map((r) => ({ id: r.id, status: r.status as IncidentStatus }));
    try {
      await Promise.all(rows.map((r) => send("PATCH", `v1/incidents/${r.id}`, { status: to })));
      setMsg({ ok: true, text: `${rows.length} incidente(s) marcado(s) como «${STATUS_LABEL[to]}».`, undo: before });
      setPicked([]);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Não consegui atualizar." });
    } finally {
      setBusy(false);
      reload();
    }
  }
  async function undo(list: { id: string; status: IncidentStatus }[]) {
    setBusy(true);
    try {
      await Promise.all(list.map((u) => send("PATCH", `v1/incidents/${u.id}`, { status: u.status })));
      setMsg({ ok: true, text: "Desfeito." });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Não consegui desfazer." });
    } finally {
      setBusy(false);
      reload();
    }
  }
  const togglePick = (id: string) => setPicked((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const chosen = (data ?? []).filter((i) => picked.includes(i.id));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Incidentes</h1>
        <p className="text-sm text-muted">Eventos com risco alto ou crítico (score de 50 ou mais) e prompts com palavra-chave monitorada. A confiança é a da categoria mais forte. Indicador de risco, requer revisão humana.
          {" "}Por padrão a fila mostra só os <strong>pendentes</strong>: ao marcar como resolvido ou falso positivo, o incidente sai da vista, mas continua no registro (filtro «Todos»).</p>
      </div>
      <fieldset className="flex flex-wrap items-end gap-4 rounded-md border border-line bg-panel px-4 py-3 text-sm">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">Filtros</legend>
        <div><label htmlFor="sev" className="mb-1 block text-muted">Severidade</label>
          <select id="sev" className="field" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">Todas</option><option value="critico">Crítico</option><option value="alto">Alto</option><option value="medio">Moderado</option><option value="baixo">Baixo</option></select></div>
        <div><label htmlFor="st" className="mb-1 block text-muted">Status</label>
          <select id="st" className="field" value={status} onChange={(e) => setStatus(e.target.value)}>
            {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}</select></div>
        <div><label htmlFor="cat" className="mb-1 block text-muted">Categoria</label>
          <select id="cat" className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Todas</option>{items.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
      </fieldset>
      {msg && (
        <p role={msg.ok ? "status" : "alert"} className={`flex flex-wrap items-center gap-3 rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>
          <span>{msg.text}</span>
          {msg.undo && <button type="button" className="btn" disabled={busy} onClick={() => void undo(msg.undo!)}>Desfazer</button>}
        </p>
      )}
      {triage && picked.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-line bg-panel2 px-3 py-2 text-sm" data-testid="bulk-bar">
          <strong>{picked.length} selecionado(s):</strong>
          <button type="button" className="btn" disabled={busy} onClick={() => void change(chosen, "em analise")}>Em análise</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void change(chosen, "resolvido")}>Resolver</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void change(chosen, "falso positivo")}>Falso positivo</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void change(chosen, "aberto")}>Reabrir</button>
          <button type="button" className="btn" onClick={() => setPicked([])}>Limpar seleção</button>
        </div>
      )}
      <Panel>
        {error && <ErrorBox message={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (data.length === 0 ? <Empty>{status === "pendentes" ? "Nenhum incidente pendente. Escolha «Todos» no filtro de status para ver os já tratados." : "Nenhum incidente com esses filtros."}</Empty> : (
          <>
            <p className="mb-2 text-sm text-muted" role="status" data-testid="incidents-total">{data.length} incidente(s){data.length === 100 ? " (os 100 mais arriscados)" : ""}</p>
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[56rem] border-collapse">
                <caption className="sr-only">Fila de incidentes, do mais arriscado ao menos</caption>
                <thead><tr>
                  {triage && <th scope="col" className="th w-8"><input type="checkbox" aria-label="Selecionar todos os incidentes da lista" checked={picked.length === data.length && data.length > 0}
                    onChange={(e) => setPicked(e.target.checked ? data.map((i) => i.id) : [])} /></th>}
                  <th scope="col" className="th">Severidade</th><th scope="col" className="th">Risco</th><th scope="col" className="th">Confiança</th>
                  <th scope="col" className="th">Usuário</th><th scope="col" className="th">Categorias</th><th scope="col" className="th">Status</th>
                  <th scope="col" className="th">Responsável</th><th scope="col" className="th">Quando</th>
                </tr></thead>
                <tbody>
                  {data.map((i) => (
                    <tr key={i.id} data-testid="incident-row" className={picked.includes(i.id) ? "bg-panel2" : ""}>
                      {triage && <td className="td"><input type="checkbox" aria-label={`Selecionar o incidente de ${i.user_id}`} checked={picked.includes(i.id)} onChange={() => togglePick(i.id)} /></td>}
                      <td className="td"><Link href={`/incidents/${i.id}`} className="inline-block rounded underline decoration-dotted underline-offset-4" aria-label={`Abrir incidente ${i.severity} de ${i.user_id}`}><SeverityBadge severity={i.severity as Severity} /></Link></td>
                      <td className="td"><RiskBar score={i.risk_score} /></td>
                      <td className="td font-mono">{pct(i.confidence)}</td>
                      <td className="td"><div className="font-medium">{i.user_id}</div><div className="text-xs text-muted">{i.department ?? "sem departamento"}</div></td>
                      <td className="td max-w-xs">
                        <Link href={`/incidents/${i.id}`} className="block hover:underline" aria-label={`Ver detalhes do incidente de ${i.user_id}`}>
                          {i.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}
                          {(i.keyword_hits ?? []).map((k) => <Chip key={`kw-${k}`}>Palavra-chave: {k}</Chip>)}
                          <span className="mt-1 block text-xs text-muted"><MaskedText text={clip(i.masked_text.replace(/\s+/g, " "), 70)} /></span>
                        </Link>
                      </td>
                      <td className="td">
                        <div className="font-medium">{STATUS_LABEL[i.status as IncidentStatus]}</div>
                        {triage && (
                          <div className="mt-1 flex flex-wrap gap-1" data-testid="quick-actions">
                            {ACTIONS[i.status as IncidentStatus].map((a) => (
                              <button key={a.to} type="button" className="btn px-2 py-0.5 text-xs" disabled={busy} onClick={() => void change([i], a.to)}
                                aria-label={`${a.label}: incidente de ${i.user_id}`}>{a.label}</button>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="td text-sm">{i.assignee_email ?? <span className="text-muted">sem responsável</span>}</td>
                      <td className="td whitespace-nowrap font-mono text-xs">{when(i.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ))}
      </Panel>
      {!triage && <p className="text-xs text-muted">Só administrador e analista alteram o status dos incidentes.</p>}
    </div>
  );
}
