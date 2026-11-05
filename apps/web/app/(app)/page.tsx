"use client";
import { useState } from "react";
import { AppUsage, DailyBars } from "@/components/charts";
import { BarList, ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, useLoad } from "@/lib/api";
import { appLabel } from "@/lib/labels";
import type { Overview } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

export default function OverviewPage() {
  const [days, setDays] = useState(14);
  const { data, error, loading, reload } = useLoad(() => api<Overview>(`v1/stats/overview?days=${days}`), [days]);
  const cats = useLoad(() => api<Record<string, number>>(`v1/stats/categories?days=${days}`), [days]);
  const { name } = useTaxonomy();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-bold">Visão geral</h1>
        <div>
          <label htmlFor="days" className="mr-2 text-sm text-muted">Período</label>
          <select id="days" className="field" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 30, 90].map((d) => <option key={d} value={d}>Últimos {d} dias</option>)}
          </select>
        </div>
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8" aria-label="Indicadores">
            <Kpi label="Prompts capturados" value={data.totals.events} />
            <Kpi label="Usuários ativos" value={data.totals.users} />
            <Kpi label="Alto risco" value={data.totals.high_risk} hint={`score ≥ ${data.high_risk_threshold}`} />
            <Kpi label="Com dado sensível" value={data.totals.with_sensitive} />
            <Kpi label="Com código" value={data.totals.with_code} />
            <Kpi label="Ações de agente" value={data.totals.agent_actions} />
            <Kpi label="Bloqueados" value={data.totals.blocked} />
            <Kpi label="Seriam bloqueados" value={data.totals.would_block} hint="políticas em monitorar" />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Eventos de alto risco por dia"><DailyBars daily={data.daily} threshold={data.high_risk_threshold} /></Panel>
            <Panel title="Uso por ferramenta"><AppUsage rows={data.by_app} label={appLabel} /></Panel>
            <Panel title="Alto risco por departamento">
              <BarList ariaLabel="Alto risco por departamento" rows={data.by_department.map((d) => ({ label: `${d.department} (${d.events})`, value: d.high_risk, extra: `de ${d.events} eventos` }))} />
              <p className="mt-2 text-xs text-muted">Entre parênteses, o total de eventos do departamento.</p>
            </Panel>
            <Panel title="Categorias mais frequentes">
              {cats.data && <BarList ariaLabel="Categorias mais frequentes" rows={Object.entries(cats.data).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([id, n]) => ({ label: name(id), value: n }))} />}
              {cats.loading && <Loading />}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
