"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Attachments } from "@/components/Attachments";
import { PromptDetailDialog } from "@/components/PromptDetail";
import { Chip, DecisionCell, Empty, ErrorBox, Loading, MaskedText, Pager, Panel, RiskBar } from "@/components/ui";
import { api, apiPage, qs, useLoad } from "@/lib/api";
import { clip, when } from "@/lib/format";
import { APP_LABEL, appLabel, intentLabel, KIND_LABEL, spanLabel } from "@/lib/labels";
import type { PromptRow, SignalsOut } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const PAGE = 20;

export default function PromptsPage() {
  const [days, setDays] = useState(14);
  const [category, setCategory] = useState("");
  const [code, setCode] = useState(false);
  const [sensitive, setSensitive] = useState(false);
  const [agent, setAgent] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [onlyRisk, setOnlyRisk] = useState(true);
  const [app, setApp] = useState("");
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [searchApplied, setSearchApplied] = useState("");
  const [intent, setIntent] = useState("");
  const [spanType, setSpanType] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [live, setLive] = useState(false);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<PromptRow | null>(null);
  const { name, groups } = useTaxonomy();

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0); };
  const counts = useLoad(() => api<Record<string, number>>(`v1/stats/categories?days=${days}`), [days]);
  const signals = useLoad(() => api<SignalsOut>(`v1/stats/signals?days=${days}`), [days]);
  const list = useLoad(() => apiPage<PromptRow[]>(`v1/events${qs({
    sort: "risk", days, limit: PAGE, offset: page * PAGE, category, app: app || undefined, kind, q: searchApplied, intent, span_type: spanType, session_id: sessionId, min_score: onlyRisk ? 1 : 0,
    has_code: code || undefined, has_sensitive: sensitive || undefined, agent_action: agent || undefined, only_blocked: blocked || undefined,
  })}`), [days, category, app, kind, searchApplied, intent, spanType, sessionId, code, sensitive, agent, blocked, onlyRisk, page]);

  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => { list.reload(); signals.reload(); counts.reload(); }, 10000);   // atualização automática, só enquanto marcada
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);
  const pick = (set: (v: string) => void, cur: string, v: string) => { set(cur === v ? "" : v); setPage(0); };
  const chipBtn = (on: boolean) => `rounded border px-2 py-1 text-xs ${on ? "border-accent bg-accent text-accent-fg" : "border-line bg-panel hover:bg-panel2"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">Análise de prompts</h1>
          <p className="text-sm text-muted">Prompts já enviados e capturados, do mais arriscado ao menos. O texto aparece mascarado. O score é um indicador de risco e exige revisão humana.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="app" className="mr-2 text-sm text-muted">Ferramenta</label>
            <select id="app" className="field" value={app} onChange={(e) => reset(setApp)(e.target.value)}>
              <option value="">Todas</option>
              {Object.entries(APP_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div>
          <label htmlFor="days" className="mr-2 text-sm text-muted">Período</label>
          <select id="days" className="field" value={days} onChange={(e) => reset(setDays)(Number(e.target.value))}>
            {[7, 14, 30, 90].map((d) => <option key={d} value={d}>Últimos {d} dias</option>)}
          </select>
          </div>
        </div>
      </div>

      <Panel title="Categorias (clique para filtrar)">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {groups.map((g) => (
            <div key={g.group}>
              <h3 className="mb-1 text-sm font-semibold">{g.group}</h3>
              <ul className="flex flex-wrap gap-1">
                {g.items.map((c) => {
                  const n = counts.data?.[c.id] ?? 0;
                  const on = category === c.id;
                  return (
                    <li key={c.id}>
                      <button type="button" aria-pressed={on} onClick={() => reset(setCategory)(on ? "" : c.id)}
                        className={`rounded border px-2 py-1 text-xs ${on ? "border-accent bg-accent text-accent-fg" : n ? "border-line bg-panel hover:bg-panel2" : "border-line bg-panel2 text-muted"}`}>
                        {c.nome} <span className="font-mono">{n}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
        {category && <p className="mt-3 text-sm">Filtrando por <strong>{name(category)}</strong>. <button type="button" className="text-accent underline" onClick={() => reset(setCategory)("")}>Limpar</button></p>}
      </Panel>

      <Panel title="Sinais do período (clique para filtrar)">
        {signals.error && <ErrorBox message={signals.error} onRetry={signals.reload} />}
        {signals.data && (
          <div className="grid gap-4 md:grid-cols-3" data-testid="signals">
            <div><h3 className="mb-1 text-sm font-semibold">Segredos e dados detectados</h3>
              <ul className="flex flex-wrap gap-1">{Object.entries(signals.data.span_types).map(([k, n]) => (
                <li key={k}><button type="button" aria-pressed={spanType === k} className={chipBtn(spanType === k)} onClick={() => pick(setSpanType, spanType, k)}>{spanLabel(k)} <span className="font-mono">{n}</span></button></li>))}
                {!Object.keys(signals.data.span_types).length && <li className="text-xs text-muted">nenhum trecho sensível no período</li>}</ul></div>
            <div><h3 className="mb-1 text-sm font-semibold">O que as pessoas pedem</h3>
              <ul className="flex flex-wrap gap-1">{Object.entries(signals.data.intents).map(([k, n]) => (
                <li key={k}><button type="button" aria-pressed={intent === k} className={chipBtn(intent === k)} onClick={() => pick(setIntent, intent, k)}>{intentLabel(k)} <span className="font-mono">{n}</span></button></li>))}
                {!Object.keys(signals.data.intents).length && <li className="text-xs text-muted">sem pedidos reconhecidos</li>}</ul></div>
            <div><h3 className="mb-1 text-sm font-semibold">Tipos de evento e ferramentas de agente</h3>
              <ul className="flex flex-wrap gap-1">{Object.entries(signals.data.kinds).map(([k, n]) => (
                <li key={k}><button type="button" aria-pressed={kind === k} className={chipBtn(kind === k)} onClick={() => pick(setKind, kind, k)}>{KIND_LABEL[k] ?? k} <span className="font-mono">{n}</span></button></li>))}
                {Object.entries(signals.data.tools).map(([k, n]) => <li key={k}><span className="rounded border border-line px-2 py-1 text-xs text-muted">{k} <span className="font-mono">{n}</span></span></li>)}</ul></div>
          </div>
        )}
      </Panel>

      <form className="flex flex-wrap items-end gap-3 rounded-md border border-line bg-panel px-4 py-3 text-sm" onSubmit={(e) => { e.preventDefault(); setSearchApplied(search.trim()); setPage(0); }}>
        <div><label htmlFor="q" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Buscar no texto mascarado</label>
          <input id="q" className="field w-64" value={search} minLength={2} maxLength={100} onChange={(e) => setSearch(e.target.value)} placeholder="ex.: contrato, credentials" /></div>
        <button className="btn">Buscar</button>
        {(searchApplied || kind || intent || spanType || sessionId) && (
          <button type="button" className="btn" onClick={() => { setSearch(""); setSearchApplied(""); setKind(""); setIntent(""); setSpanType(""); setSessionId(""); setPage(0); }}>Limpar filtros de sinais</button>
        )}
        <label className="ml-auto flex items-center gap-2"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Atualizar sozinho a cada 10 s</label>
      </form>
      {sessionId && <p className="text-sm">Mostrando só a sessão <code className="font-mono text-xs">{sessionId}</code>. <button type="button" className="text-accent underline" onClick={() => reset(setSessionId)("")}>Ver todas</button></p>}

      <fieldset className="flex flex-wrap gap-x-5 gap-y-2 rounded-md border border-line bg-panel px-4 py-3 text-sm">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">Filtros</legend>
        <label className="flex items-center gap-2"><input type="checkbox" checked={code} onChange={(e) => reset(setCode)(e.target.checked)} /> Contém código</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={sensitive} onChange={(e) => reset(setSensitive)(e.target.checked)} /> Dado sensível</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={agent} onChange={(e) => reset(setAgent)(e.target.checked)} /> Ação de agente</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={blocked} onChange={(e) => reset(setBlocked)(e.target.checked)} /> Só bloqueados (ou que seriam)</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={onlyRisk} onChange={(e) => reset(setOnlyRisk)(e.target.checked)} /> Só com risco</label>
      </fieldset>

      <div>
        <Panel>
          {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
          {list.loading && !list.data && <Loading />}
          {list.data && (list.data.items.length === 0 ? <Empty>Nenhum prompt com esses filtros.</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] border-collapse">
                <caption className="sr-only">Prompts capturados, ordenados por risco</caption>
                <thead><tr>
                  <th scope="col" className="th">Quando</th><th scope="col" className="th">Usuário</th><th scope="col" className="th">Ferramenta</th>
                  <th scope="col" className="th">Prompt (mascarado)</th><th scope="col" className="th">Risco</th><th scope="col" className="th">Decisão</th>
                </tr></thead>
                <tbody>
                  {list.data.items.map((p) => (
                    <tr key={p.event_id} className={selected?.event_id === p.event_id ? "bg-accent-soft" : ""} data-testid="prompt-row">
                      <td className="td whitespace-nowrap font-mono text-xs">{when(p.occurred_at)}</td>
                      <td className="td"><div className="font-medium">{p.user_id}</div><div className="text-xs text-muted">{p.department ?? "sem departamento"}</div></td>
                      <td className="td">{appLabel(p.app)}<div className="text-xs text-muted">{p.personal_account ? "conta pessoal" : "conta corporativa"}</div></td>
                      <td className="td max-w-xs">
                        <button type="button" onClick={() => setSelected(p)} aria-label={`Ver detalhes do prompt de ${p.user_id}`} className="block w-full text-left hover:underline">
                          {p.kind === "tool_call" && <span className="mr-1 rounded border border-line px-1 text-xs text-muted">{p.tool_name ?? "ação"}</span>}
                          <MaskedText text={clip(p.masked_text.replace(/\s+/g, " "), 120)} />
                        </button>
                        <Attachments row={p} compact />
                        <div className="mt-1">{p.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}
                          {(p.flags.intents ?? []).map((i) => <span key={i} className={`mr-1 text-xs ${i === "declara_confidencial" ? "font-semibold text-high" : "text-muted"}`}>{intentLabel(i)}</span>)}</div>
                      </td>
                      <td className="td"><RiskBar score={p.risk_score} /></td>
                      <td className="td"><DecisionCell decision={p.decision} would={p.would_decide} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {list.data && <Pager page={page} pageSize={PAGE} total={list.data.total} onPage={setPage} />}
        </Panel>

      </div>

      <PromptDetailDialog row={selected} onClose={() => setSelected(null)} onReviewed={list.reload}
        onSession={(id) => { setSessionId(id); setSelected(null); setPage(0); }} />
    </div>
  );
}
