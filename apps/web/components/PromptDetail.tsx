"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Dialog } from "@/components/Dialog";
import { Attachments } from "@/components/Attachments";
import { FeedbackForm } from "@/components/FeedbackForm";
import { MaskedText } from "@/components/ui";
import { whenFull } from "@/lib/format";
import { appLabel, intentLabel, KIND_LABEL, spanLabel } from "@/lib/labels";
import type { Feedback, PromptRow } from "@/lib/types";

/** Detalhe de um prompt (texto sempre mascarado). Usado em "Análise de prompts" e "Todos os prompts". */
export function PromptDetailDialog({ row: incoming, onClose, onSession, onPerson, onReviewed }: {
  row: PromptRow | null; onClose: () => void; onSession: (sessionId: string) => void; onPerson?: (userId: string) => void; onReviewed?: () => void;
}) {
  const [saved, setSaved] = useState<{ id: string; fb: Feedback } | null>(null);
  useEffect(() => setSaved(null), [incoming?.event_id]);
  const row = incoming && saved?.id === incoming.event_id ? { ...incoming, feedback: saved.fb } : incoming;
  return (
    <Dialog open={!!row} onClose={onClose} title="Detalhe do prompt" wide>
      {row && (
        <div className="space-y-3 text-sm" data-testid="prompt-detail">
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted">Usuário</dt><dd>{onPerson ? <button type="button" className="text-accent underline" onClick={() => onPerson(row.user_id)}>{row.user_id}</button> : row.user_id}</dd>
                <dt className="text-muted">Departamento</dt><dd>{row.department ?? "—"}</dd>
                <dt className="text-muted">Ferramenta</dt><dd>{appLabel(row.app)} ({row.personal_account ? "pessoal" : "corporativa"})</dd>
                <dt className="text-muted">Quando</dt><dd>{whenFull(row.occurred_at)}</dd>
                <dt className="text-muted">Tipo</dt><dd>{KIND_LABEL[row.kind] ?? row.kind}{row.tool_name ? ` (${row.tool_name})` : ""}</dd>
                {row.session_id && <><dt className="text-muted">Sessão</dt><dd><button type="button" className="text-accent underline" onClick={() => onSession(row.session_id!)}>ver todos os eventos desta sessão</button></dd></>}
              </dl>
              {(row.flags.intents ?? []).length > 0 && <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">O que foi pedido</h3><p>{(row.flags.intents ?? []).map(intentLabel).join(", ")}</p></div>}
              {(row.spans ?? []).length > 0 && <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Trechos sensíveis detectados</h3>
                <ul className="space-y-1 font-mono text-xs">{(row.spans ?? []).map((sp, i) => <li key={i}>{spanLabel(sp.type)} · {sp.masked}</li>)}</ul></div>}
              {(row.attachments ?? []).length > 0 && <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Arquivos anexados</h3><Attachments row={row} />
                <p className="mt-1 text-xs text-muted">Só o nome, o tamanho e o tipo são coletados; o conteúdo do arquivo não. O nome sugere o risco, não prova o que há dentro.</p></div>}
              <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Prompt (mascarado)</h3><div className="rounded border border-line bg-panel2 p-2"><MaskedText text={row.masked_text} block /></div></div>
              <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Motivos do score</h3>
                <ul className="space-y-1 font-mono text-xs">{row.reasons.map((r, i) => <li key={i}>+{r.contribution} · {r.rule}</li>)}{!row.reasons.length && <li>sem motivos de risco</li>}</ul></div>
              {row.policy_hits.length > 0 && <div><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Políticas que casaram</h3>
                <ul className="space-y-1 text-xs">{row.policy_hits.map((h) => <li key={h.policy_id}>{h.name} <span className="text-muted">({h.mode === "monitor" ? "monitorar" : "aplicar"})</span></li>)}</ul></div>}
              <FeedbackForm key={`${row.event_id}:${row.feedback?.updated_at ?? ""}`} row={row} onSaved={(fb) => { setSaved({ id: row.event_id, fb }); onReviewed?.(); }} />
              <p className="text-xs text-muted">Indicador de risco, requer revisão humana.</p>
              {row.incident_id && <Link href={`/incidents/${row.incident_id}`} className="btn-primary inline-block">Abrir incidente</Link>}
            </div>
      )}
      <div className="mt-4 flex justify-end"><button type="button" className="btn" onClick={onClose}>Fechar</button></div>
    </Dialog>
  );
}
