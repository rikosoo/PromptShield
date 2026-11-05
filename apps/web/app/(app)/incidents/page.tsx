"use client";
import Link from "next/link";
import { useState } from "react";
import { Chip, DecisionCell, Empty, ErrorBox, Loading, MaskedText, Panel, RiskBar, SeverityBadge } from "@/components/ui";
import { api, qs, useLoad } from "@/lib/api";
import { clip, pct, when } from "@/lib/format";
import { STATUS_LABEL, STATUSES } from "@/lib/labels";
import type { Incident, IncidentStatus, Severity } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

export default function IncidentsPage() {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const { name, items } = useTaxonomy();
  const { data, error, loading, reload } = useLoad(() => api<Incident[]>(`v1/incidents${qs({ severity, status, category, limit: 100 })}`), [severity, status, category]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Incidentes</h1>
        <p className="text-sm text-muted">Eventos com risco alto ou crítico (score de 60 ou mais). A confiança é a da categoria mais forte. Indicador de risco, requer revisão humana.</p>
      </div>
      <fieldset className="flex flex-wrap items-end gap-4 rounded-md border border-line bg-panel px-4 py-3 text-sm">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">Filtros</legend>
        <div><label htmlFor="sev" className="mb-1 block text-muted">Severidade</label>
          <select id="sev" className="field" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">Todas</option><option value="critico">Crítico</option><option value="alto">Alto</option></select></div>
        <div><label htmlFor="st" className="mb-1 block text-muted">Status</label>
          <select id="st" className="field" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todos</option>{STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></div>
        <div><label htmlFor="cat" className="mb-1 block text-muted">Categoria</label>
          <select id="cat" className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Todas</option>{items.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
      </fieldset>
      <Panel>
        {error && <ErrorBox message={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (data.length === 0 ? <Empty>Nenhum incidente com esses filtros.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] border-collapse">
              <caption className="sr-only">Fila de incidentes, do mais arriscado ao menos</caption>
              <thead><tr>
                <th scope="col" className="th">Severidade</th><th scope="col" className="th">Risco</th><th scope="col" className="th">Confiança</th>
                <th scope="col" className="th">Usuário</th><th scope="col" className="th">Categorias</th><th scope="col" className="th">Status</th>
                <th scope="col" className="th">Responsável</th><th scope="col" className="th">Quando</th>
              </tr></thead>
              <tbody>
                {data.map((i) => (
                  <tr key={i.id} data-testid="incident-row">
                    <td className="td"><Link href={`/incidents/${i.id}`} className="inline-block rounded underline decoration-dotted underline-offset-4" aria-label={`Abrir incidente ${i.severity} de ${i.user_id}`}><SeverityBadge severity={i.severity as Severity} /></Link></td>
                    <td className="td"><RiskBar score={i.risk_score} /></td>
                    <td className="td font-mono">{pct(i.confidence)}</td>
                    <td className="td"><div className="font-medium">{i.user_id}</div><div className="text-xs text-muted">{i.department ?? "sem departamento"}</div></td>
                    <td className="td max-w-xs">{i.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}<div className="mt-1 text-xs text-muted"><MaskedText text={clip(i.masked_text.replace(/\s+/g, " "), 70)} /></div></td>
                    <td className="td">{STATUS_LABEL[i.status as IncidentStatus]}<div className="mt-1"><DecisionCell decision={i.decision} would={i.would_decide} /></div></td>
                    <td className="td text-sm">{i.assignee_email ?? <span className="text-muted">sem responsável</span>}</td>
                    <td className="td whitespace-nowrap font-mono text-xs">{when(i.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </Panel>
    </div>
  );
}
