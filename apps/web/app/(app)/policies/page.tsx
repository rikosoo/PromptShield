"use client";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { ActionBadge, Chip, Empty, ErrorBox, Loading, MaskedText, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { ACTION_LABEL } from "@/lib/labels";
import type { Action, Policy, PolicyDraft, Simulation } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const blank = (): PolicyDraft => ({ name: "", description: null, enabled: true, scope: {}, match: { categories: [] }, action: "alert", mode: "monitor" });
const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function PoliciesPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const { name, groups } = useTaxonomy();
  const { data, error, loading, reload } = useLoad(() => api<Policy[]>("v1/policies"), []);
  const [editing, setEditing] = useState<{ id: string | null; draft: PolicyDraft } | null>(null);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const d = editing?.draft;
  const patch = (p: Partial<PolicyDraft>) => setEditing((e) => (e ? { ...e, draft: { ...e.draft, ...p } } : e));

  const open = (p?: Policy) => {
    setSim(null);
    setFormErr(null);
    setEditing(p ? { id: p.id, draft: { name: p.name, description: p.description, enabled: p.enabled, scope: p.scope, match: p.match, action: p.action, mode: p.mode } } : { id: null, draft: blank() });
  };

  async function simulate() {
    if (!d) return;
    setBusy(true);
    setFormErr(null);
    try {
      setSim(await send<Simulation>("POST", "v1/policies/simulate", { policy: { ...d, name: d.name || "simulação" }, days }));
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : "Erro ao simular");
    } finally {
      setBusy(false);
    }
  }

  async function save(ev: FormEvent) {
    ev.preventDefault();
    if (!editing || !d) return;
    setBusy(true);
    setFormErr(null);
    try {
      await (editing.id ? send("PUT", `v1/policies/${editing.id}`, d) : send("POST", "v1/policies", d));
      setEditing(null);
      reload();
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : "Erro ao salvar");
    } finally {
      setBusy(false);
    }
  }

  const cats = d?.match.categories ?? [];
  const toggleCat = (id: string) => patch({ match: { ...d!.match, categories: cats.includes(id) ? cats.filter((c) => c !== id) : [...cats, id] } });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">Políticas</h1>
          <p className="max-w-3xl text-sm text-muted">Toda política nasce em <strong>monitorar</strong>: a decisão devolvida é sempre &quot;permitir&quot; e a que teria sido tomada fica registrada. <strong>Aplicar</strong> é opção explícita por política.</p>
        </div>
        {isAdmin && <button type="button" className="btn-primary" onClick={() => open()}>Nova política</button>}
      </div>
      {!isAdmin && <p className="rounded border border-line bg-panel p-3 text-sm text-muted">Só o administrador cria ou altera políticas. Você pode consultar e simular.</p>}
      <Panel>
        {error && <ErrorBox message={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (data.length === 0 ? <Empty>Nenhuma política cadastrada.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse">
              <caption className="sr-only">Políticas do tenant</caption>
              <thead><tr><th scope="col" className="th">Política</th><th scope="col" className="th">Quando</th><th scope="col" className="th">Escopo</th><th scope="col" className="th">Ação</th><th scope="col" className="th">Modo</th><th scope="col" className="th"><span className="sr-only">Editar</span></th></tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id} data-testid="policy-row">
                    <th scope="row" className="td text-left font-medium">{p.name}{!p.enabled && <span className="ml-2 text-xs text-muted">(desligada)</span>}<div className="text-xs font-normal text-muted">versão {p.version}</div></th>
                    <td className="td">{(p.match.categories ?? []).map((c) => <Chip key={c}>{name(c)}</Chip>)}{p.match.min_score ? <Chip>score ≥ {p.match.min_score}</Chip> : null}{!(p.match.categories ?? []).length && !p.match.min_score && <span className="text-muted">qualquer categoria</span>}</td>
                    <td className="td text-xs">{Object.entries(p.scope).filter(([, v]) => v.length).map(([k, v]) => <div key={k}>{k === "departments" ? "Departamentos" : k === "apps" ? "Ferramentas" : "Grupos"}: {v.join(", ")}</div>)}{!Object.values(p.scope).some((v) => v.length) && <span className="text-muted">todos</span>}</td>
                    <td className="td"><ActionBadge action={p.action} /></td>
                    <td className="td"><span className={`rounded px-2 py-0.5 font-mono text-xs font-semibold ${p.mode === "enforce" ? "bg-crit-bg text-crit" : "bg-low-bg text-low"}`}>{p.mode === "enforce" ? "aplicar" : "monitorar"}</span></td>
                    <td className="td"><button type="button" className="btn" onClick={() => open(p)}>{isAdmin ? "Editar" : "Ver e simular"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </Panel>

      <Dialog open={!!editing} onClose={() => setEditing(null)} title={editing?.id ? "Política" : "Nova política"} wide>
        {d && (
          <form onSubmit={save} className="space-y-4 text-sm">
            <fieldset disabled={!isAdmin} className="space-y-4">
              <div><label htmlFor="pname" className="mb-1 block font-medium">Nome</label><input id="pname" required className="field w-full" value={d.name} onChange={(e) => patch({ name: e.target.value })} /></div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div><label htmlFor="pact" className="mb-1 block font-medium">Ação</label>
                  <select id="pact" className="field w-full" value={d.action} onChange={(e) => patch({ action: e.target.value as Action })}>
                    {(Object.keys(ACTION_LABEL) as Action[]).map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}</select></div>
                <fieldset><legend className="mb-1 font-medium">Modo</legend>
                  <label className="mr-4 inline-flex items-center gap-1"><input type="radio" name="mode" checked={d.mode === "monitor"} onChange={() => patch({ mode: "monitor" })} /> Monitorar</label>
                  <label className="inline-flex items-center gap-1"><input type="radio" name="mode" checked={d.mode === "enforce"} onChange={() => patch({ mode: "enforce" })} /> Aplicar</label>
                  {d.mode === "enforce" && <p className="mt-1 text-xs text-crit">Em modo aplicar, a ação passa a valer. Simule antes.</p>}</fieldset>
              </div>
              <fieldset><legend className="mb-1 font-medium">Categorias (nenhuma marcada = qualquer categoria)</legend>
                <div className="grid max-h-56 gap-3 overflow-y-auto rounded border border-line p-2 sm:grid-cols-2">
                  {groups.map((g) => (
                    <div key={g.group}><div className="text-xs font-semibold text-muted">{g.group}</div>
                      {g.items.map((c) => <label key={c.id} className="flex items-center gap-2 py-0.5"><input type="checkbox" checked={cats.includes(c.id)} onChange={() => toggleCat(c.id)} /> {c.nome}</label>)}</div>
                  ))}
                </div></fieldset>
              <div className="grid gap-4 sm:grid-cols-3">
                <div><label htmlFor="pdep" className="mb-1 block font-medium">Departamentos (separe por vírgula)</label><input id="pdep" className="field w-full" value={(d.scope.departments ?? []).join(", ")} onChange={(e) => patch({ scope: { ...d.scope, departments: csv(e.target.value) } })} /></div>
                <div><label htmlFor="papp" className="mb-1 block font-medium">Ferramentas (ex.: claude_code)</label><input id="papp" className="field w-full" value={(d.scope.apps ?? []).join(", ")} onChange={(e) => patch({ scope: { ...d.scope, apps: csv(e.target.value) } })} /></div>
                <div><label htmlFor="pscore" className="mb-1 block font-medium">Score mínimo</label><input id="pscore" type="number" min={0} max={100} className="field w-full" value={d.match.min_score ?? 0} onChange={(e) => patch({ match: { ...d.match, min_score: Number(e.target.value) } })} /></div>
              </div>
              <label className="flex items-center gap-2"><input type="checkbox" checked={d.enabled} onChange={(e) => patch({ enabled: e.target.checked })} /> Política ligada</label>
            </fieldset>

            <div className="rounded border border-line bg-panel2 p-3">
              <div className="flex flex-wrap items-end gap-3">
                <div><label htmlFor="sdays" className="mb-1 block font-medium">Simular sobre os últimos</label>
                  <select id="sdays" className="field" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90].map((n) => <option key={n} value={n}>{n} dias</option>)}</select></div>
                <button type="button" className="btn" onClick={simulate} disabled={busy}>Simular</button>
              </div>
              {sim && (
                <div className="mt-3 space-y-2" role="region" aria-label="Resultado da simulação" data-testid="simulation">
                  <p><strong className="font-mono text-lg" data-testid="sim-matched">{sim.matched}</strong> de {sim.events_evaluated} eventos casariam, de <strong>{sim.matched_users}</strong> usuário(s). Em {sim.would_be_stronger_than_current} deles a ação seria mais forte que a atual.</p>
                  {sim.truncated && <p className="text-xs text-muted">Foram avaliados só os {sim.events_evaluated} eventos mais recentes de {sim.events_in_period}.</p>}
                  {sim.ignored_scope.length > 0 && <p className="text-xs text-muted">O escopo por grupo não foi considerado na simulação.</p>}
                  <p className="text-xs text-muted">{sim.note}</p>
                  {sim.examples.length > 0 && <ul className="space-y-1 text-xs">{sim.examples.map((x) => <li key={x.event_id}><span className="font-mono">{x.risk_score}</span> · {x.user_id}: <MaskedText text={x.masked_text} /></li>)}</ul>}
                </div>
              )}
            </div>
            {formErr && <ErrorBox message={formErr} />}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => setEditing(null)}>{isAdmin ? "Cancelar" : "Fechar"}</button>
              {isAdmin && <button type="submit" className="btn-primary" disabled={busy}>Salvar</button>}
            </div>
          </form>
        )}
      </Dialog>
    </div>
  );
}
