"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PromptDetailDialog } from "@/components/PromptDetail";
import { AlertStatusBadge, Chip, Empty, ErrorBox, Loading, Pager, Panel, RiskBar, SeverityTag } from "@/components/ui";
import { api, apiPage, qs, useLoad } from "@/lib/api";
import { clip, when } from "@/lib/format";
import { appLabel, KIND_LABEL } from "@/lib/labels";
import type { PersonRow, PromptRow } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const PAGE = 15;

/** Usuários: procurar uma pessoa (contém ou começa com) e ver todos os prompts dela. */
export default function UsersPage() {
  const { name } = useTaxonomy();
  const [days, setDays] = useState(30);
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const [mode, setMode] = useState<"contains" | "prefix">("contains");
  const [sel, setSel] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<PromptRow | null>(null);

  useEffect(() => { const t = setTimeout(() => setApplied(q.trim()), 250); return () => clearTimeout(t); }, [q]);   // espera a pessoa parar de digitar
  const people = useLoad(() => api<PersonRow[]>(`v1/people${qs({ q: applied || undefined, mode, days, limit: 200 })}`), [applied, mode, days]);
  const prompts = useLoad(() => (sel ? apiPage<PromptRow[]>(`v1/events${qs({ user_id: sel, days, sort: "recent", limit: PAGE, offset: page * PAGE })}`) : Promise.resolve(null)),
    [sel, days, page]);
  const choose = (id: string) => { setSel(id === sel ? null : id); setPage(0); setOpen(null); };
  const person = people.data?.find((p) => p.user_id === sel);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Usuários</h1>
        <p className="text-sm text-muted">Procure uma pessoa pelo identificador que o coletor envia (e-mail ou usuário da máquina) e veja todos os prompts dela. Indicador de risco, não prova de má conduta: exige revisão humana.</p>
      </div>
      <form className="grid items-end gap-3 md:grid-cols-[minmax(0,2fr)_1fr_1fr]" onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }} aria-label="Procurar usuário">
        <div><label htmlFor="uq" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Procurar</label>
          <input id="uq" className="field w-full" maxLength={100} value={q} onChange={(e) => setQ(e.target.value)} placeholder="ex.: ana, DTC- ou @empresa.com" /></div>
        <div><label htmlFor="umode" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Como procurar</label>
          <select id="umode" className="field w-full" value={mode} onChange={(e) => setMode(e.target.value as "contains" | "prefix")}>
            <option value="contains">Contém o texto</option><option value="prefix">Começa com o texto</option>
          </select></div>
        <div><label htmlFor="udays" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Período</label>
          <select id="udays" className="field w-full" value={days} onChange={(e) => { setDays(Number(e.target.value)); setPage(0); }}>
            {[7, 14, 30, 90, 365].map((d) => <option key={d} value={d}>Últimos {d} dias</option>)}
          </select></div>
      </form>

      <Panel title={`Pessoas (${people.data?.length ?? 0}${people.data?.length === 200 ? "+" : ""})`}>
        {people.error && <ErrorBox message={people.error} onRetry={people.reload} />}
        {people.loading && !people.data && <Loading />}
        {people.data && (people.data.length === 0 ? <Empty>Ninguém encontrado neste período{applied ? ` para «${applied}»` : ""}.</Empty> : (
          <div className="relative max-h-96 overflow-auto">
            <table className="w-full min-w-[44rem] border-collapse" data-testid="users-table">
              <caption className="sr-only">Pessoas que usaram IA no período</caption>
              <thead><tr><th scope="col" className="th">Usuário</th><th scope="col" className="th">Departamento</th><th scope="col" className="th">Grupos</th><th scope="col" className="th">Prompts</th>
                <th scope="col" className="th">Risco alto</th><th scope="col" className="th">Maior risco</th><th scope="col" className="th">Última atividade</th></tr></thead>
              <tbody>
                {people.data.map((p) => (
                  <tr key={p.user_id} className={sel === p.user_id ? "bg-panel2" : ""}>
                    <th scope="row" className="td text-left font-normal"><button type="button" aria-pressed={sel === p.user_id} onClick={() => choose(p.user_id)} className="font-medium text-accent hover:underline">{p.user_id}</button></th>
                    <td className="td">{p.department ?? "—"}</td>
                    <td className="td">{(p.groups ?? []).length ? p.groups!.map((g) => <Chip key={g}>{g}</Chip>) : <span className="text-muted">—</span>}</td>
                    <td className="td font-mono">{p.events}</td>
                    <td className="td font-mono">{p.high_risk}</td>
                    <td className="td"><RiskBar score={p.max_risk} /></td>
                    <td className="td whitespace-nowrap font-mono text-xs">{when(p.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </Panel>

      {sel && (
        <Panel title={`Prompts de ${sel}`} action={<Link className="text-sm text-accent underline" href={`/history?user=${encodeURIComponent(sel)}&days=${days}`}>Abrir em Todos os prompts (mais filtros)</Link>}>
          {person && <p className="mb-2 text-sm text-muted">{person.events} prompt(s) no período · {person.high_risk} de risco alto · {person.department ?? "sem departamento"}</p>}
          {prompts.error && <ErrorBox message={prompts.error} onRetry={prompts.reload} />}
          {prompts.loading && !prompts.data && <Loading />}
          {prompts.data && (prompts.data.items.length === 0 ? <Empty>Nenhum prompt desta pessoa no período.</Empty> : (
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[44rem] border-collapse" data-testid="user-prompts">
                <caption className="sr-only">Prompts da pessoa, do mais recente ao mais antigo</caption>
                <thead><tr><th scope="col" className="th">Quando</th><th scope="col" className="th">Ferramenta</th><th scope="col" className="th">Prompt (mascarado)</th>
                  <th scope="col" className="th">Score</th><th scope="col" className="th">Severidade</th><th scope="col" className="th">Status do alerta</th></tr></thead>
                <tbody>
                  {prompts.data.items.map((p) => (
                    <tr key={p.event_id}>
                      <td className="td whitespace-nowrap font-mono text-xs">{when(p.occurred_at)}</td>
                      <td className="td">{appLabel(p.app)}<div className="text-xs text-muted">{KIND_LABEL[p.kind] ?? p.kind}</div></td>
                      <td className="td max-w-sm">
                        <button type="button" onClick={() => setOpen(p)} aria-label={`Ver detalhes do prompt de ${p.user_id}`} className="block w-full text-left hover:underline">{clip(p.masked_text.replace(/\s+/g, " "), 160)}</button>
                        <div className="mt-1">{p.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}{(p.flags.keyword_hits ?? []).map((k) => <Chip key={`kw-${k}`}>Palavra-chave: {k}</Chip>)}</div>
                      </td>
                      <td className="td"><RiskBar score={p.risk_score} /></td>
                      <td className="td"><SeverityTag severity={p.severity} /></td>
                      <td className="td"><AlertStatusBadge status={p.alert_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {prompts.data && <Pager page={page} pageSize={PAGE} total={prompts.data.total} onPage={setPage} />}
        </Panel>
      )}
      <PromptDetailDialog row={open} onClose={() => setOpen(null)} onSession={() => setOpen(null)} onReviewed={prompts.reload} />
    </div>
  );
}
