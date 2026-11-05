"use client";
import Link from "next/link";
import { use, useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { canTriage, useSession } from "@/components/session";
import { Chip, DecisionCell, ErrorBox, Loading, MaskedText, Panel, RiskBar, SeverityBadge } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { pct, whenFull } from "@/lib/format";
import { appLabel, STATUS_LABEL, STATUSES } from "@/lib/labels";
import type { DirectoryUser, Incident } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

export default function IncidentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me, tenant } = useSession();
  const { name } = useTaxonomy();
  const { data: inc, error, loading, reload } = useLoad(() => api<Incident>(`v1/incidents/${id}`), [id]);
  const people = useLoad(() => (canTriage(me.role) ? api<DirectoryUser[]>("v1/users/directory") : Promise.resolve([] as DirectoryUser[])), [me.role]);
  const [msg, setMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [ask, setAsk] = useState(false);
  const [why, setWhy] = useState("");
  const [original, setOriginal] = useState<string | null>(null);
  const [origErr, setOrigErr] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    setSaveErr(null);
    try {
      await send("PATCH", `v1/incidents/${id}`, body);
      setMsg("Incidente atualizado.");
      reload();
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : "Erro ao salvar");
    }
  }

  async function reveal(ev: FormEvent) {
    ev.preventDefault();
    setOrigErr(null);
    try {
      const r = await send<{ text: string }>("POST", `v1/events/${inc!.event_id}/original`, { justification: why });
      setOriginal(r.text);
      setAsk(false);
      setWhy("");
    } catch (e) {
      setOrigErr(e instanceof Error ? e.message : "Erro");
    }
  }

  if (loading && !inc) return <Loading />;
  if (error || !inc) return <div className="space-y-3"><ErrorBox message={error ?? "Incidente não encontrado"} onRetry={reload} /><Link href="/incidents" className="text-accent underline">Voltar à fila</Link></div>;

  const triage = canTriage(me.role);
  return (
    <div className="space-y-4">
      <p><Link href="/incidents" className="text-sm text-accent underline">← Fila de incidentes</Link></p>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold">Incidente</h1>
        <SeverityBadge severity={inc.severity} />
        <RiskBar score={inc.risk_score} />
        <span className="text-sm text-muted">confiança {pct(inc.confidence)}</span>
        {tenant.is_demo && <span className="text-xs text-muted">(dados de exemplo)</span>}
      </div>
      <p className="text-sm text-muted">Indicador de risco, requer revisão humana. Não é prova de má conduta.</p>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(18rem,1fr)]">
        <div className="space-y-4">
          <Panel title="Evidência (texto mascarado)">
            <div className="rounded border border-line bg-panel2 p-3" data-testid="evidence"><MaskedText text={inc.masked_text} block /></div>
            <div className="mt-3">{inc.categories.map((c) => <Chip key={c.id}>{name(c.id)} · {pct(c.confidence)}</Chip>)}</div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
              <DecisionCell decision={inc.decision} would={inc.would_decide} />
              {triage && inc.has_original && !original && <button type="button" className="btn" onClick={() => { setAsk(true); setOrigErr(null); }}>Ver texto original</button>}
              {!inc.has_original && <span className="text-xs text-muted">O texto original não é guardado para este evento.</span>}
              {inc.has_original && !triage && <span className="text-xs text-muted">Só administrador e analista podem pedir o texto original.</span>}
            </div>
            {original !== null && (
              <div className="mt-3 rounded border border-crit bg-crit-bg p-3 text-sm" role="region" aria-label="Texto original">
                <p className="mb-1 font-semibold text-crit">Texto original. Este acesso foi registrado na auditoria.</p>
                <pre className="whitespace-pre-wrap break-words font-mono text-sm text-fg" data-testid="original">{original}</pre>
                <button type="button" className="btn mt-2" onClick={() => setOriginal(null)}>Ocultar</button>
              </div>
            )}
          </Panel>
          <Panel title="Motivos do score">
            <ul className="space-y-1 font-mono text-sm">{inc.reasons.map((r, i) => <li key={i}>+{r.contribution} · {r.rule}</li>)}</ul>
          </Panel>
          <Panel title="Linha do tempo">
            <ol className="space-y-2 border-l-2 border-line pl-4 text-sm" data-testid="timeline">
              {inc.timeline?.map((t, i) => <li key={i}><span className="font-mono text-xs text-muted">{whenFull(t.at)}</span><br />{t.what}</li>)}
            </ol>
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="Contexto">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted">Usuário</dt><dd>{inc.user_id}</dd>
              <dt className="text-muted">Departamento</dt><dd>{inc.department ?? "—"}</dd>
              <dt className="text-muted">Ferramenta</dt><dd>{appLabel(inc.app)} ({inc.personal_account ? "conta pessoal" : "conta corporativa"})</dd>
            </dl>
          </Panel>
          <Panel title="Triagem">
            <div className="space-y-3 text-sm">
              <div><label htmlFor="status" className="mb-1 block text-muted">Status</label>
                <select id="status" className="field w-full" value={inc.status} disabled={!triage} onChange={(e) => patch({ status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></div>
              <div><label htmlFor="assignee" className="mb-1 block text-muted">Responsável</label>
                <select id="assignee" className="field w-full" value={inc.assignee_id ?? ""} disabled={!triage} onChange={(e) => patch({ assignee_id: e.target.value || null })}>
                  <option value="">Sem responsável</option>{people.data?.map((u) => <option key={u.id} value={u.id}>{u.display_name ?? u.email}</option>)}</select></div>
              {!triage && <p className="text-xs text-muted">Seu papel só permite leitura.</p>}
              <p role="status" className="text-xs text-low">{msg}</p>
              {saveErr && <ErrorBox message={saveErr} />}
            </div>
          </Panel>
          <Panel title="Resposta recomendada">
            <ul className="list-disc space-y-2 pl-5 text-sm" data-testid="recommendations">{inc.recommendations?.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </Panel>
        </div>
      </div>

      <Dialog open={ask} onClose={() => setAsk(false)} title="Ver o texto original">
        <form onSubmit={reveal} className="space-y-3 text-sm">
          <p>O texto original contém dados que a plataforma mascara por padrão. Informe o motivo: ele fica registrado na auditoria com o seu nome.</p>
          <div><label htmlFor="why" className="mb-1 block font-medium">Justificativa (mínimo de 10 caracteres)</label>
            <textarea id="why" required minLength={10} rows={3} className="field w-full" value={why} onChange={(e) => setWhy(e.target.value)} /></div>
          {origErr && <ErrorBox message={origErr} />}
          <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={() => setAsk(false)}>Cancelar</button>
            <button type="submit" className="btn-primary" disabled={why.trim().length < 10}>Ver texto original</button></div>
        </form>
      </Dialog>
    </div>
  );
}
