"use client";
import Link from "next/link";
import { useState } from "react";
import { AppUsage, DailyBars } from "@/components/charts";
import { BarList, ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, useLoad } from "@/lib/api";
import { appLabel } from "@/lib/labels";
import { collectorHealth, detectionHealth, LEVEL_LABEL, type HealthLevel } from "@/lib/health";
import type { DevicesOut, Overview, QualitySummary } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const LEVEL_CLASS: Record<HealthLevel, string> = {
  ok: "border-low bg-low-bg text-low", warn: "border-med bg-med-bg text-med", crit: "border-crit bg-crit-bg text-crit", unknown: "border-line text-muted",
};
const pct = (n: number | null) => (n === null ? "—" : `${Math.round(n * 100)}%`);

function LevelTag({ level }: { level: HealthLevel }) {
  return <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${LEVEL_CLASS[level]}`}>{LEVEL_LABEL[level]}</span>;
}

/** Confiabilidade do painel: falso positivo e cobertura dos coletores, para não passar falsa sensação de segurança. */
function Reliability({ days }: { days: number }) {
  const quality = useLoad(() => api<QualitySummary>(`v1/feedback/summary?days=${days}`), [days]);
  const devices = useLoad(() => api<DevicesOut>("v1/devices"), []);
  const det = detectionHealth(quality.data);
  const col = devices.data ? collectorHealth(devices.data.devices, new Date()) : null;
  return (
    <div className="grid gap-4 xl:grid-cols-2" data-testid="reliability">
      <Panel title="Qualidade da detecção (falsos positivos)" action={<LevelTag level={det.level} />}>
        {quality.loading && !quality.data && <Loading />}
        {quality.error && <p className="text-sm text-muted">Indisponível para o seu perfil ou sem dados de revisão.</p>}
        {quality.data && (
          <>
            <dl className="grid grid-cols-3 gap-3">
              <div><dt className="text-xs text-muted">Falso positivo</dt><dd className="font-mono text-2xl font-semibold" data-testid="fp-rate">{pct(det.falsePositiveRate)}</dd></div>
              <div><dt className="text-xs text-muted">Faltou pegar</dt><dd className="font-mono text-2xl font-semibold">{pct(det.missedRate)}</dd></div>
              <div><dt className="text-xs text-muted">Revisado</dt><dd className="font-mono text-2xl font-semibold">{pct(det.reviewCoverage)}</dd></div>
            </dl>
            <p className="mt-2 text-xs text-muted">{det.note} <Link href="/quality" className="underline">Ver por categoria</Link></p>
          </>
        )}
      </Panel>
      <Panel title="Cobertura dos coletores" action={col && <LevelTag level={col.level} />}>
        {devices.loading && !devices.data && <Loading />}
        {devices.error && <ErrorBox message={devices.error} onRetry={devices.reload} />}
        {col && (
          <>
            <p className="mb-2 text-sm" data-testid="collector-summary">
              {col.sensors.total} sensor(es): {col.sensors.ativo} ativo(s), {col.sensors.inativo + col.sensors.nunca} inativo(s)/nunca enviou.
              {col.confirmedCoverage !== null && <> Cobertura confirmada: <strong>{pct(col.confirmedCoverage)}</strong> das IAs habilitadas enviaram evento nos últimos 7 dias.</>}
            </p>
            {col.rows.length === 0 ? <p className="text-sm text-muted">Nenhuma IA com coleta habilitada ainda.</p> : (
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-muted"><th className="py-1">IA</th><th>Habilitada</th><th>Capturando</th><th>Parou</th><th>Aguardando</th><th /></tr></thead>
                <tbody>
                  {col.rows.map((r) => (
                    <tr key={r.id} className="border-t border-line">
                      <td className="py-1">{r.label}</td><td>{r.enabled}</td><td>{r.capturing}</td><td>{r.stopped}</td><td>{r.waiting}</td><td><LevelTag level={r.level} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-2 text-xs text-muted">{col.note} <Link href="/sensors" className="underline">Ver sensores</Link></p>
          </>
        )}
      </Panel>
    </div>
  );
}

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
          <Reliability days={days} />
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
