"use client";
import { Fragment, useEffect, useState } from "react";
import { Attachments } from "@/components/Attachments";
import { VERDICT_LABEL } from "@/components/FeedbackForm";
import { PromptDetailDialog } from "@/components/PromptDetail";
import { useSession } from "@/components/session";
import { AlertStatusBadge, Chip, Empty, ErrorBox, Loading, Pager, Panel, RiskBar, SeverityTag } from "@/components/ui";
import { apiPage, api, qs, useLoad } from "@/lib/api";
import { clip, splitMasks, when } from "@/lib/format";
import { ALERT_STATUS_LABEL, APP_LABEL, appLabel, KIND_LABEL, SEVERITY_LABEL } from "@/lib/labels";
import type { PersonRow, PromptRow } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const PAGE = 25;

/** Texto mascarado com a palavra buscada destacada (os trechos mascarados mantêm o destaque próprio). */
function Highlighted({ text, term }: { text: string; term: string }) {
  const t = term.trim().toLowerCase();
  return (
    <span className="font-mono text-sm">
      {splitMasks(text).map((p, i) => {
        if (p.mask) return <mark key={i}>{p.text}</mark>;
        if (!t) return <span key={i}>{p.text}</span>;
        const low = p.text.toLowerCase();
        const out: React.ReactNode[] = [];
        let at = 0;
        for (let k = low.indexOf(t); k >= 0; k = low.indexOf(t, at)) {
          out.push(p.text.slice(at, k), <strong key={k} className="rounded bg-accent-soft px-0.5" data-testid="hit">{p.text.slice(k, k + t.length)}</strong>);
          at = k + t.length;
        }
        out.push(p.text.slice(at));
        return <Fragment key={i}>{out}</Fragment>;
      })}
    </span>
  );
}

export default function HistoryPage() {
  const { me } = useSession();
  const canExport = me.role === "admin" || me.role === "auditor";
  const [person, setPerson] = useState("");
  const [personApplied, setPersonApplied] = useState("");
  const [word, setWord] = useState("");
  const [wordApplied, setWordApplied] = useState("");
  const [app, setApp] = useState("");
  const [kind, setKind] = useState("");
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const [alertStatus, setAlertStatus] = useState("");
  const [department, setDepartment] = useState("");
  const [days, setDays] = useState(30);
  const [onlyRisk, setOnlyRisk] = useState(false);
  const [personalOnly, setPersonalOnly] = useState(false);
  const [withFile, setWithFile] = useState(false);
  const [review, setReview] = useState("");
  const [sensor, setSensor] = useState<{ id: string; host: string } | null>(null);
  const [urlRead, setUrlRead] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<PromptRow | null>(null);
  const { name, groups } = useTaxonomy();

  useEffect(() => {      // vindo do painel de Sensores: /history?sensor=<id>&host=<nome da máquina>
    const sp = new URLSearchParams(window.location.search);
    const id = sp.get("sensor");
    if (id && /^[0-9a-f-]{36}$/i.test(id)) setSensor({ id, host: (sp.get("host") ?? "").slice(0, 200) });
    setUrlRead(true);
  }, []);
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0); };
  const people = useLoad(() => api<PersonRow[]>(`v1/people${qs({ days, limit: 100 })}`), [days]);
  const filters = {
    days, user_q: personApplied, q: wordApplied, app: app || undefined, kind, category, severity: severity || undefined, alert_status: alertStatus || undefined, department,
    session_id: sessionId, sensor: sensor?.id, has_attachment: withFile ? true : undefined, review, min_score: onlyRisk ? 1 : 0, personal_account: personalOnly ? true : undefined,
  };
  const list = useLoad(() => (urlRead ? apiPage<PromptRow[]>(`v1/events${qs({ ...filters, sort: "recent", limit: PAGE, offset: page * PAGE })}`)
    : Promise.resolve({ items: [] as PromptRow[], total: 0 })),     // espera ler o ?sensor= da URL antes da primeira busca (senão piscaria a lista inteira)
    [days, personApplied, wordApplied, app, kind, category, severity, alertStatus, department, onlyRisk, personalOnly, withFile, review, sessionId, sensor?.id, urlRead, page]);
  const departments = Array.from(new Set((people.data ?? []).map((p) => p.department).filter((d): d is string => !!d))).sort();
  const anyFilter = sessionId || personApplied || wordApplied || app || kind || category || severity || alertStatus || department || onlyRisk || personalOnly || withFile || review || sensor;
  const clear = () => { setPerson(""); setPersonApplied(""); setWord(""); setWordApplied(""); setApp(""); setKind(""); setCategory(""); setSeverity(""); setAlertStatus(""); setDepartment(""); setOnlyRisk(false); setPersonalOnly(false); setWithFile(false); setReview(""); setSessionId(""); setSensor(null); setPage(0); };
  const choosePerson = (id: string) => { setPerson(id); setPersonApplied(id); setSelected(null); setPage(0); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Todos os prompts</h1>
        <p className="text-sm text-muted">Tudo que foi capturado, do mais recente ao mais antigo, com quem escreveu. A busca vale para o texto já mascarado; o original nunca aparece aqui. Consultar e exportar fica registrado na auditoria.</p>
      </div>

      <form className="grid gap-3 rounded-md border border-line bg-panel px-4 py-3 text-sm md:grid-cols-2 xl:grid-cols-4"
        onSubmit={(e) => { e.preventDefault(); setPersonApplied(person.trim()); setWordApplied(word.trim()); setPage(0); }}>
        <div><label htmlFor="person" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Pessoa (nome ou e-mail)</label>
          <input id="person" className="field w-full" list="people-list" value={person} maxLength={100} onChange={(e) => setPerson(e.target.value)} placeholder="ex.: ana@empresa.com" />
          <datalist id="people-list">{(people.data ?? []).map((p) => <option key={p.user_id} value={p.user_id} />)}</datalist></div>
        <div><label htmlFor="word" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Palavra-chave (prompt ou arquivo)</label>
          <input id="word" className="field w-full" value={word} minLength={2} maxLength={100} onChange={(e) => setWord(e.target.value)} placeholder="ex.: contrato, senha, nome de arquivo" /></div>
        <div><label htmlFor="app" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Ferramenta</label>
          <select id="app" className="field w-full" value={app} onChange={(e) => reset(setApp)(e.target.value)}>
            <option value="">Todas</option>{Object.entries(APP_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label htmlFor="days" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Período</label>
          <select id="days" className="field w-full" value={days} onChange={(e) => reset(setDays)(Number(e.target.value))}>
            {[1, 7, 14, 30, 90, 365].map((d) => <option key={d} value={d}>{d === 1 ? "Hoje" : `Últimos ${d} dias`}</option>)}</select></div>
        <div><label htmlFor="kind" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Tipo</label>
          <select id="kind" className="field w-full" value={kind} onChange={(e) => reset(setKind)(e.target.value)}>
            <option value="">Todos</option>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label htmlFor="category" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Categoria</label>
          <select id="category" className="field w-full" value={category} onChange={(e) => reset(setCategory)(e.target.value)}>
            <option value="">Todas</option>
            {groups.map((g) => <optgroup key={g.group} label={g.group}>{g.items.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</optgroup>)}</select></div>
        <div><label htmlFor="severity" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Severidade</label>
          <select id="severity" className="field w-full" value={severity} onChange={(e) => reset(setSeverity)(e.target.value)}>
            <option value="">Todas</option>{(["baixo", "medio", "alto", "critico"] as const).map((k) => <option key={k} value={k}>{SEVERITY_LABEL[k]}</option>)}</select></div>
        <div><label htmlFor="astatus" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Status do alerta</label>
          <select id="astatus" className="field w-full" value={alertStatus} onChange={(e) => reset(setAlertStatus)(e.target.value)}>
            <option value="">Todos</option>{Object.entries(ALERT_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label htmlFor="review" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Revisão humana</label>
          <select id="review" className="field w-full" value={review} onChange={(e) => reset(setReview)(e.target.value)}>
            <option value="">Todas</option><option value="pending">Ainda sem revisão</option><option value="reviewed">Já revisadas</option>
            <option value="falso_positivo">Falso positivo</option><option value="faltou">Faltou pegar</option><option value="correta">Análise correta</option></select></div>
        <div><label htmlFor="dept" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Departamento</label>
          <select id="dept" className="field w-full" value={department} onChange={(e) => reset(setDepartment)(e.target.value)}>
            <option value="">Todos</option>{departments.map((d) => <option key={d} value={d}>{d}</option>)}</select></div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 md:col-span-2 xl:col-span-4">
          <label className="flex items-center gap-2"><input type="checkbox" checked={onlyRisk} onChange={(e) => reset(setOnlyRisk)(e.target.checked)} /> Só com risco</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={withFile} onChange={(e) => reset(setWithFile)(e.target.checked)} /> Só com arquivo anexado</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={personalOnly} onChange={(e) => reset(setPersonalOnly)(e.target.checked)} /> Só conta pessoal</label>
          <button className="btn-primary">Buscar</button>
          {anyFilter && <button type="button" className="btn" onClick={clear}>Limpar filtros</button>}
          {canExport && <a className="btn ml-auto" data-testid="export-csv" download href={`/api/proxy/v1/events/export.csv${qs({ ...filters, limit: 20000 })}`}>Exportar CSV (auditado)</a>}
        </div>
      </form>

      {sensor && <p className="text-sm" data-testid="sensor-chip">Mostrando só os prompts do sensor <strong>{sensor.host || sensor.id}</strong>. <button type="button" className="text-accent underline" onClick={() => reset(setSensor)(null)}>Ver todos</button></p>}
      {sessionId && <p className="text-sm">Mostrando só a sessão <code className="font-mono text-xs">{sessionId}</code>. <button type="button" className="text-accent underline" onClick={() => reset(setSessionId)("")}>Ver todas</button></p>}

      <Panel title={`Pessoas no período (${people.data?.length ?? 0}) — clique para filtrar`}>
        {people.error && <ErrorBox message={people.error} onRetry={people.reload} />}
        {people.data && (people.data.length === 0 ? <Empty>Ninguém usou IA neste período.</Empty> : (
          <ul className="flex flex-wrap gap-2" data-testid="people">
            {people.data.map((p) => (
              <li key={p.user_id}>
                <button type="button" aria-pressed={personApplied === p.user_id} onClick={() => choosePerson(personApplied === p.user_id ? "" : p.user_id)}
                  className={`rounded border px-2 py-1 text-left text-xs ${personApplied === p.user_id ? "border-accent bg-accent text-accent-fg" : "border-line bg-panel hover:bg-panel2"}`}>
                  <span className="font-medium">{p.user_id}</span> <span className="font-mono">{p.events}</span>
                  {p.high_risk > 0 && <span className="ml-1 font-semibold text-high">{p.high_risk} de risco alto</span>}
                  <span className="block opacity-80">{p.department ?? "sem departamento"} · última {when(p.last_seen)}</span>
                </button>
              </li>
            ))}
          </ul>
        ))}
      </Panel>

      <Panel>
        {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
        {list.loading && !list.data && <Loading />}
        {list.data && (list.data.items.length === 0 ? <Empty>Nenhum prompt com esses filtros.</Empty> : (
          <>
            <p className="mb-2 text-sm text-muted" role="status" data-testid="history-total">{list.data.total} resultado(s)</p>
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[48rem] border-collapse">
                <caption className="sr-only">Todos os prompts capturados, do mais recente ao mais antigo</caption>
                <thead><tr>
                  <th scope="col" className="th">Quando</th><th scope="col" className="th">Pessoa</th><th scope="col" className="th">Ferramenta</th>
                  <th scope="col" className="th">Prompt (mascarado)</th><th scope="col" className="th">Score</th><th scope="col" className="th">Severidade</th><th scope="col" className="th">Status do alerta</th>
                </tr></thead>
                <tbody>
                  {list.data.items.map((p) => (
                    <tr key={p.event_id} data-testid="history-row">
                      <td className="td whitespace-nowrap font-mono text-xs">{when(p.occurred_at)}</td>
                      <td className="td"><button type="button" className="font-medium text-accent hover:underline" onClick={() => choosePerson(p.user_id)} title="Ver só esta pessoa">{p.user_id}</button>
                        <div className="text-xs text-muted">{p.department ?? "sem departamento"}</div></td>
                      <td className="td">{appLabel(p.app)}<div className="text-xs text-muted">{KIND_LABEL[p.kind] ?? p.kind}{p.personal_account ? " · conta pessoal" : ""}</div></td>
                      <td className="td max-w-sm">
                        <button type="button" onClick={() => setSelected(p)} aria-label={`Ver detalhes do prompt de ${p.user_id}`} className="block w-full text-left hover:underline">
                          {p.kind === "tool_call" && <span className="mr-1 rounded border border-line px-1 text-xs text-muted">{p.tool_name ?? "ação"}</span>}
                          <Highlighted text={clip(p.masked_text.replace(/\s+/g, " "), 160)} term={wordApplied} />
                        </button>
                        <Attachments row={p} compact />
                        {p.feedback && <span className="mr-1 text-xs text-muted" data-testid="reviewed-badge">revisado: {VERDICT_LABEL[p.feedback.verdict]}</span>}
                        <div className="mt-1">{p.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}</div>
                      </td>
                      <td className="td"><RiskBar score={p.risk_score} /></td>
                      <td className="td"><SeverityTag severity={p.severity} /></td>
                      <td className="td"><AlertStatusBadge status={p.alert_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ))}
        {list.data && <Pager page={page} pageSize={PAGE} total={list.data.total} onPage={setPage} />}
      </Panel>

      <PromptDetailDialog row={selected} onClose={() => setSelected(null)} onPerson={choosePerson} onReviewed={list.reload}
        onSession={(id) => { setSessionId(id); setSelected(null); setPage(0); }} />
    </div>
  );
}
