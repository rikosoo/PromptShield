"use client";
import { useState } from "react";
import { Spark } from "@/components/charts";
import { Empty, ErrorBox, Loading, Panel, RiskBar } from "@/components/ui";
import { api, useLoad } from "@/lib/api";
import type { RiskStats } from "@/lib/types";

export default function RiskPage() {
  const [days, setDays] = useState(14);
  const { data, error, loading, reload } = useLoad(() => api<RiskStats>(`v1/stats/risk?days=${days}`), [days]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">Risco por usuário e departamento</h1>
          <p className="mt-1 max-w-3xl rounded border border-line bg-panel2 p-2 text-sm" data-testid="risk-disclaimer" role="note">
            {data?.disclaimer ?? "Indicador de risco, requer revisão humana. Não é prova de má conduta."}
          </p>
        </div>
        <div>
          <label htmlFor="rdays" className="mr-2 text-sm text-muted">Período</label>
          <select id="rdays" className="field" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 30, 90].map((d) => <option key={d} value={d}>Últimos {d} dias</option>)}
          </select>
        </div>
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <Panel title="Departamentos">
            {data.departments.length === 0 ? <Empty>Sem atividade no período.</Empty> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] border-collapse" data-testid="dept-risk">
                  <caption className="sr-only">Indicador de risco por departamento (média dos usuários)</caption>
                  <thead><tr><th scope="col" className="th">Departamento</th><th scope="col" className="th">Indicador (média)</th><th scope="col" className="th">Usuários</th><th scope="col" className="th">Em risco alto</th><th scope="col" className="th">Eventos</th><th scope="col" className="th">Evolução</th></tr></thead>
                  <tbody>{data.departments.map((d) => (
                    <tr key={d.department}>
                      <th scope="row" className="td text-left font-medium">{d.department}</th>
                      <td className="td"><RiskBar score={d.score} /></td>
                      <td className="td font-mono">{d.users}</td><td className="td font-mono">{d.users_high}</td><td className="td font-mono">{d.events}</td>
                      <td className="td"><Spark series={d.series} days={data.days} label={`Evolução do indicador de ${d.department}`} /></td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
          </Panel>
          <Panel title="Usuários (maior indicador primeiro)">
            {data.users.length === 0 ? <Empty>Sem atividade no período.</Empty> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[48rem] border-collapse" data-testid="user-risk">
                  <caption className="sr-only">Indicador de risco por usuário</caption>
                  <thead><tr><th scope="col" className="th">Usuário</th><th scope="col" className="th">Departamento</th><th scope="col" className="th">Indicador</th><th scope="col" className="th">Por quê</th><th scope="col" className="th">Eventos / alto risco</th><th scope="col" className="th">Evolução</th></tr></thead>
                  <tbody>{data.users.map((u) => (
                    <tr key={u.user_id}>
                      <th scope="row" className="td text-left font-mono text-xs">{u.user_id}</th>
                      <td className="td">{u.department ?? "—"}</td>
                      <td className="td"><RiskBar score={u.score} /></td>
                      <td className="td text-xs">{u.reasons.length ? <ul>{u.reasons.map((r) => <li key={r.rule}>{r.rule} (+{r.contribution})</li>)}</ul> : <span className="text-muted">sem risco no período</span>}</td>
                      <td className="td font-mono">{u.events} / {u.high_events}</td>
                      <td className="td"><Spark series={u.series} days={data.days} label={`Evolução do indicador de ${u.user_id}`} /></td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
            <p className="mt-3 text-xs text-muted">Fórmula versão {data.score_version}: maior risco de um evento no período + bônus de repetição (5 por evento adicional com risco ≥ 35, no máximo 20). O departamento é a média dos usuários com atividade.</p>
          </Panel>
        </>
      )}
    </div>
  );
}
