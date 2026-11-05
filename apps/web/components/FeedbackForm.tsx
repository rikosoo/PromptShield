"use client";
import { useState } from "react";
import { canTriage, useSession } from "@/components/session";
import { send } from "@/lib/api";
import type { Feedback, PromptRow, Verdict } from "@/lib/types";
import { useTaxonomy } from "@/lib/useTaxonomy";

export const VERDICT_LABEL: Record<Verdict, string> = { correta: "Análise correta", falso_positivo: "Falso positivo", faltou: "Faltou pegar" };

/** Revisão humana da análise. Alimenta a medição de qualidade; não muda a decisão nem a política deste evento. */
export function FeedbackForm({ row, onSaved }: { row: PromptRow; onSaved: (fb: Feedback) => void }) {
  const { me } = useSession();
  const { items, name } = useTaxonomy();
  const current = row.feedback ?? null;
  const [verdict, setVerdict] = useState<Verdict | "">(current?.verdict ?? "");
  const [wrong, setWrong] = useState<string[]>(current?.wrong_categories ?? []);
  const [missing, setMissing] = useState<string[]>(current?.missing_categories ?? []);
  const [note, setNote] = useState(current?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reported = row.categories.map((c) => c.id);
  const toggle = (list: string[], set: (v: string[]) => void, id: string) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  if (!canTriage(me.role)) {
    return current ? <p className="text-sm" data-testid="feedback-readonly">Revisão: <strong>{VERDICT_LABEL[current.verdict]}</strong></p> : <p className="text-xs text-muted">Ainda sem revisão humana.</p>;
  }
  const save = async () => {
    if (!verdict) return;
    setBusy(true); setError("");
    try {
      const fb = await send<Feedback>("POST", `v1/events/${row.event_id}/feedback`, { verdict, wrong_categories: verdict === "falso_positivo" ? wrong : [], missing_categories: verdict === "faltou" ? missing : [], note: note.trim() || null });
      onSaved(fb);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const pick = "rounded border px-2 py-1 text-xs";
  const on = "border-accent bg-accent text-accent-fg";
  const off = "border-line bg-panel hover:bg-panel2";
  return (
    <fieldset className="space-y-2 rounded border border-line p-3" data-testid="feedback-form">
      <legend className="px-1 text-xs font-semibold uppercase text-muted">Esta análise está certa?</legend>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Veredito">
        {(Object.keys(VERDICT_LABEL) as Verdict[]).map((v) => (
          <button key={v} type="button" aria-pressed={verdict === v} className={`${pick} ${verdict === v ? on : off}`} onClick={() => setVerdict(v)}>{VERDICT_LABEL[v]}</button>
        ))}
      </div>
      {verdict === "falso_positivo" && (
        <div role="group" aria-label="Categorias erradas"><p className="mb-1 text-xs text-muted">Qual categoria sinalizada está errada?</p>
          {reported.length ? reported.map((id) => <button key={id} type="button" aria-pressed={wrong.includes(id)} className={`${pick} mr-1 ${wrong.includes(id) ? on : off}`} onClick={() => toggle(wrong, setWrong, id)}>{name(id)}</button>) : <span className="text-xs text-muted">Nada foi sinalizado neste evento.</span>}</div>
      )}
      {verdict === "faltou" && (
        <div><label htmlFor="fb-missing" className="mb-1 block text-xs text-muted">Qual categoria deveria ter sido detectada?</label>
          <select id="fb-missing" className="field" value="" onChange={(e) => e.target.value && toggle(missing, setMissing, e.target.value)}>
            <option value="">Escolher…</option>{items.filter((c) => !reported.includes(c.id)).map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</select>
          <span className="ml-2">{missing.map((id) => <button key={id} type="button" className={`${pick} mr-1 ${on}`} onClick={() => toggle(missing, setMissing, id)} aria-label={`Remover ${name(id)}`}>{name(id)} ×</button>)}</span></div>
      )}
      <div><label htmlFor="fb-note" className="mb-1 block text-xs text-muted">Observação (opcional, não vai para a exportação; não coloque dado pessoal)</label>
        <input id="fb-note" className="field w-full" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></div>
      {error && <p role="alert" className="text-sm text-crit">{error}</p>}
      <div className="flex items-center gap-3">
        <button type="button" className="btn-primary" disabled={busy || !verdict || (verdict === "falso_positivo" && !wrong.length) || (verdict === "faltou" && !missing.length)} onClick={save}>Salvar revisão</button>
        {current && <span className="text-xs text-muted" data-testid="feedback-saved">Revisão atual: {VERDICT_LABEL[current.verdict]}</span>}
      </div>
    </fieldset>
  );
}
