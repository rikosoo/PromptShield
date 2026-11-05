"use client";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Chip, ErrorBox, Kpi, Loading, MaskedText, Panel, RiskBar } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { PilotSummary, ReviewItem } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

const pct = (v: number | null) => (v === null ? "sem dados" : `${(v * 100).toFixed(1)}%`);
const dur = (s: number | null) => (s === null ? "sem alerta ainda" : s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : `${(s / 3600).toFixed(1)} h`);
const LABELS = [["verdadeiro_positivo", "Verdadeiro positivo"], ["falso_positivo", "Falso positivo"], ["incerto", "Incerto"]] as const;

export default function PilotPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const canReview = me.role === "admin" || me.role === "analista";
  const { name } = useTaxonomy();
  const sum = useLoad(() => api<PilotSummary>("v1/pilot/summary"), []);
  const queue = useLoad(() => (canReview ? api<ReviewItem[]>("v1/pilot/reviews?limit=20") : Promise.resolve([] as ReviewItem[])), [canReview]);
  const [expected, setExpected] = useState("");
  const [days, setDays] = useState("");
  const [sampleSize, setSampleSize] = useState(50);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); sum.reload(); queue.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro" }); } finally { setBusy(false); }
  }
  const saveConfig = (ev: FormEvent) => { ev.preventDefault(); void run(() => send("PUT", "v1/pilot/config", { ...(expected ? { expected_users: Number(expected) } : {}), ...(days ? { pilot_days: Number(days) } : {}) }), "Configuração do piloto salva."); };
  const start = () => { if (!sum.data?.started_at || confirm("O piloto já foi iniciado. Marcar um novo início zera a janela das métricas. Continuar?")) void run(() => send("PUT", "v1/pilot/config", { start: true }), "Piloto iniciado agora."); };
  const sample = () => run(async () => { const r = await send<{ size: number }>("POST", "v1/pilot/samples", { size: sampleSize }); if (r.size === 0) throw new Error("Não há eventos sinalizados novos para sortear."); }, "Amostra sorteada.");
  const label = (id: string, l: string) => run(() => send("PATCH", `v1/pilot/reviews/${id}`, { label: l }), "Revisão registrada.");
  async function report() {
    setBusy(true);
    setMsg(null);
    try {
      const d = sum.data!;
      const end = new Date().toISOString().slice(0, 10);
      const startDay = (d.started_at ?? new Date(Date.now() - 29 * 86_400_000).toISOString()).slice(0, 10);
      const r = await send<{ id: string }>("POST", "v1/reports", { kind: "piloto", format: "pdf", start: startDay, end });
      setReportId(r.id);
      setMsg({ ok: true, text: "Relatório final gerado." });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro" }); } finally { setBusy(false); }
  }

  const d = sum.data;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Piloto de 30 dias (só monitorar)</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">Nenhuma política é aplicada no piloto: tudo fica em <strong>monitorar</strong>. Os números abaixo vêm do banco; as metas são sugestões a combinar com o cliente (docs/piloto.md).</p>
      </div>
      {sum.error && <ErrorBox message={sum.error} onRetry={sum.reload} />}
      {sum.loading && !d && <Loading />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Indicadores do piloto">
            <Kpi label="Dia do piloto" value={d.day ? `${d.day} de ${d.pilot_days}` : "não iniciado"} hint={d.started_at ? `início ${whenFull(d.started_at)}` : "clique em Iniciar piloto"} />
            <Kpi label="Cobertura de usuários" value={pct(d.coverage.rate)} hint={`${d.coverage.active_users} de ${d.coverage.expected_users ?? "?"} esperados`} />
            <Kpi label="Falso positivo (revisado)" value={pct(d.false_positive.rate)} hint={d.false_positive.ci95 ? `IC 95%: ${pct(d.false_positive.ci95[0])} a ${pct(d.false_positive.ci95[1])}` : "sem revisões"} />
            <Kpi label="Tempo até o 1º alerta" value={dur(d.time_to_first_alert_seconds)} hint={d.first_alert_at ? whenFull(d.first_alert_at) : undefined} />
          </div>
          <p role="status" data-testid="monitor-only" className={`rounded border p-2 text-sm ${d.monitor_only ? "border-line bg-panel2" : "border-crit text-crit"}`}>
            {d.monitor_only ? "Modo só monitorar confirmado: todas as políticas em monitorar e nenhuma decisão aplicada." : "ATENÇÃO: há política em modo aplicar ou decisões aplicadas. Um piloto deve rodar só em monitorar."}
          </p>
          {d.false_positive.small_sample && <p className="text-sm text-muted" data-testid="small-sample">Amostra pequena: só {d.false_positive.decided} itens decididos (mínimo {d.false_positive.min_reviews} para a taxa ser estável). {d.false_positive.scope}.</p>}

          {isAdmin && (
            <Panel title="Configuração">
              <form onSubmit={saveConfig} className="flex flex-wrap items-end gap-3 text-sm">
                <div><label htmlFor="pexp" className="mb-1 block font-medium">Usuários esperados</label><input id="pexp" type="number" min={1} className="field w-32" value={expected} placeholder={String(d.coverage.expected_users ?? "")} onChange={(e) => setExpected(e.target.value)} /></div>
                <div><label htmlFor="pdays" className="mb-1 block font-medium">Duração (dias)</label><input id="pdays" type="number" min={1} max={180} className="field w-28" value={days} placeholder={String(d.pilot_days)} onChange={(e) => setDays(e.target.value)} /></div>
                <button className="btn" disabled={busy}>Salvar</button>
                <button type="button" className="btn-primary" disabled={busy} onClick={start}>Iniciar piloto agora</button>
              </form>
            </Panel>
          )}

          <Panel title="Revisão por amostragem (falso positivo)">
            {!canReview ? <p className="text-sm text-muted">Só administrador e analista revisam.</p> : (
              <>
                <div className="mb-3 flex flex-wrap items-end gap-3 text-sm">
                  <div><label htmlFor="psize" className="mb-1 block font-medium">Tamanho da amostra</label><input id="psize" type="number" min={1} max={500} className="field w-28" value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value))} /></div>
                  <button type="button" className="btn" disabled={busy} onClick={sample}>Sortear amostra</button>
                  <span className="text-muted">{d.false_positive.pending} pendente(s), {d.false_positive.reviewed} revisado(s)</span>
                </div>
                {queue.data?.length === 0 && <p className="py-4 text-center text-sm text-muted">Nenhum item pendente. Sorteie uma amostra entre os eventos sinalizados.</p>}
                <ul className="space-y-3">
                  {queue.data?.map((r) => (
                    <li key={r.id} className="rounded border border-line p-3" data-testid="review-item">
                      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs"><RiskBar score={r.risk_score} />{r.categories.map((c) => <Chip key={c.id}>{name(c.id)}</Chip>)}<span className="text-muted">{r.user_id} · {r.app}</span></div>
                      <MaskedText text={r.masked_text} block />
                      <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="O alerta estava certo?">
                        {LABELS.map(([v, l]) => <button key={v} type="button" className="btn" disabled={busy} onClick={() => label(r.id, v)}>{l}</button>)}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p className="mt-3 text-xs text-muted">A taxa vale para os eventos que o produto sinalizou; não mede o que passou sem ser sinalizado. &quot;Incerto&quot; não entra na taxa.</p>
          </Panel>

          <Panel title="Relatório final">
            <p className="mb-2 text-sm text-muted">PDF com cobertura, falsos positivos, tempo até o primeiro alerta, modo monitorar e metas sugeridas.</p>
            <button type="button" className="btn-primary" disabled={busy} onClick={report}>Gerar relatório final (PDF)</button>
            {reportId && <a className="ml-3 text-accent underline" href={`/api/proxy/v1/reports/${reportId}/download`} download>Baixar PDF</a>}
          </Panel>
          {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "" : "text-crit"}`}>{msg.text}</p>}
        </>
      )}
    </div>
  );
}
