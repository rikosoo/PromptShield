"use client";
import { useState } from "react";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, useLoad } from "@/lib/api";
import type { QualitySummary } from "@/lib/types";

export default function QualityPage() {
  const { me } = useSession();
  const [days, setDays] = useState(90);
  const s = useLoad(() => api<QualitySummary>(`v1/feedback/summary?days=${days}`), [days]);
  const canExport = me.role === "admin" || me.role === "auditor";
  const pct = (n: number) => `${Math.round(n * 100)}%`;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">Qualidade da detecção</h1>
          <p className="text-sm text-muted">Onde a análise acertou e errou, segundo a revisão de pessoas. Revise prompts em <strong>Todos os prompts</strong> (abra um prompt e responda &quot;Esta análise está certa?&quot;).</p>
        </div>
        <div className="flex items-end gap-3">
          <div><label htmlFor="days" className="mr-2 text-sm text-muted">Período</label>
            <select id="days" className="field" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[30, 90, 180, 365].map((d) => <option key={d} value={d}>Últimos {d} dias</option>)}</select></div>
          {canExport && <a className="btn" data-testid="export-feedback" download href={`/api/proxy/v1/feedback/export.jsonl?days=${days}`}>Exportar revisões (auditado)</a>}
        </div>
      </div>
      {s.error && <ErrorBox message={s.error} onRetry={s.reload} />}
      {s.loading && !s.data && <Loading />}
      {s.data && (
        <>
          <Panel title="Resumo">
            <dl className="grid gap-4 sm:grid-cols-4" data-testid="quality-summary">
              <div><dt className="text-xs text-muted">Prompts no período</dt><dd className="text-2xl font-bold">{s.data.events}</dd></div>
              <div><dt className="text-xs text-muted">Revisados</dt><dd className="text-2xl font-bold">{s.data.reviewed} <span className="text-sm font-normal text-muted">({pct(s.data.coverage)})</span></dd></div>
              <div><dt className="text-xs text-muted">Análise correta</dt><dd className="text-2xl font-bold">{s.data.verdicts.correta}</dd></div>
              <div><dt className="text-xs text-muted">Falso positivo / faltou pegar</dt><dd className="text-2xl font-bold">{s.data.verdicts.falso_positivo} / {s.data.verdicts.faltou}</dd></div>
            </dl>
            <p className="mt-3 text-xs text-muted">{s.data.note}</p>
          </Panel>
          <Panel title="Por categoria (mais problemas primeiro)">
            {s.data.categories.length === 0 ? <Empty>Nenhuma revisão ainda.</Empty> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] border-collapse">
                  <caption className="sr-only">Revisões por categoria</caption>
                  <thead><tr><th scope="col" className="th">Categoria</th><th scope="col" className="th">Revisados</th><th scope="col" className="th">Falsos positivos</th><th scope="col" className="th">Faltou pegar</th><th scope="col" className="th">Precisão estimada</th></tr></thead>
                  <tbody>
                    {s.data.categories.map((c) => (
                      <tr key={c.id} data-testid="quality-row"><td className="td">{c.nome}</td><td className="td font-mono">{c.reviewed}</td><td className="td font-mono">{c.wrong}</td><td className="td font-mono">{c.missed}</td>
                        <td className="td font-mono">{c.precision_estimate === null ? <span className="text-muted" title={`precisa de ${s.data!.min_for_estimate} revisões`}>amostra pequena</span> : pct(c.precision_estimate)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
