"use client";
import type { ReactNode } from "react";
import { ACTION_LABEL, SEVERITY_CLASS, SEVERITY_LABEL, severityOf } from "@/lib/labels";
import { splitMasks } from "@/lib/format";
import type { Action, Severity } from "@/lib/types";

export function Panel({ title, children, className = "", action }: { title?: string; children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <section className={`min-w-0 rounded-md border border-line bg-panel p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-md border border-line bg-panel p-4" data-testid="kpi">
      <div className="font-mono text-3xl font-semibold tabular-nums">{value}</div>
      <div className="text-sm text-muted">{label}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`inline-block whitespace-nowrap rounded px-2 py-0.5 font-mono text-xs font-semibold uppercase ${SEVERITY_CLASS[severity]}`}>{SEVERITY_LABEL[severity]}</span>;
}

export function RiskBar({ score }: { score: number }) {
  const sev = severityOf(score);
  const color = { baixo: "bg-low", medio: "bg-med", alto: "bg-high", critico: "bg-crit" }[sev];
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap font-mono text-sm font-semibold" title={`Indicador de risco ${score} de 100 (${SEVERITY_LABEL[sev]})`}>
      <span aria-hidden className="inline-block h-1.5 w-12 overflow-hidden rounded-full border border-line bg-panel2"><span className={`block h-full ${color}`} style={{ width: `${score}%` }} /></span>
      <span>{score}</span>
      <span className="sr-only">{`de 100, ${SEVERITY_LABEL[sev]}`}</span>
    </span>
  );
}

const ACTION_CLASS: Record<Action, string> = {
  allow: "bg-low-bg text-low", alert: "bg-med-bg text-med", mask: "bg-med-bg text-med", ask_justification: "bg-med-bg text-med", block: "bg-crit-bg text-crit",
};
export function ActionBadge({ action }: { action: Action }) {
  return <span className={`inline-block whitespace-nowrap rounded px-2 py-0.5 font-mono text-xs font-semibold ${ACTION_CLASS[action]}`}>{ACTION_LABEL[action]}</span>;
}

/** Decisão tomada e, quando a política estava em monitorar, a que teria sido tomada. */
export function DecisionCell({ decision, would }: { decision: Action; would: Action }) {
  return (
    <div className="space-y-0.5">
      <ActionBadge action={decision} />
      {would !== decision && <div className="text-xs text-muted">teria sido: {ACTION_LABEL[would]}</div>}
    </div>
  );
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="mb-1 mr-1 inline-block rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-xs">{children}</span>;
}

/** Texto já mascarado pela API; as máscaras ficam em destaque. */
export function MaskedText({ text, block = false }: { text: string; block?: boolean }) {
  return (
    <span className={block ? "block whitespace-pre-wrap break-words font-mono text-sm" : "font-mono text-sm"}>
      {splitMasks(text).map((p, i) => (p.mask ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
    </span>
  );
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return <p role="status" className="py-6 text-sm text-muted">{label}</p>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-crit bg-crit-bg p-3 text-sm text-crit">
      {message}
      {onRetry && <button type="button" onClick={onRetry} className="ml-3 rounded border border-crit px-2 py-0.5 font-medium underline">Tentar de novo</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function BarList({ rows, max, ariaLabel }: { rows: { label: string; value: number; extra?: string }[]; max?: number; ariaLabel: string }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <Empty>Sem dados no período.</Empty>;
  return (
    <ul aria-label={ariaLabel} className="space-y-2">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,9rem)_1fr_3rem] items-center gap-2 text-sm">
          <span className="truncate" title={r.label}>{r.label}</span>
          <span aria-hidden className="h-2 overflow-hidden rounded-full border border-line bg-panel2"><span className="bar-fill block h-full bg-accent" style={{ width: `${(r.value / top) * 100}%` }} /></span>
          <span className="text-right font-mono tabular-nums">{r.value}{r.extra && <span className="sr-only"> {r.extra}</span>}</span>
        </li>
      ))}
    </ul>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Paginação" className="mt-3 flex items-center justify-between gap-2 text-sm">
      <span className="text-muted" data-testid="total">{total} resultado{total === 1 ? "" : "s"}</span>
      <span className="flex items-center gap-2">
        <button type="button" className="btn" disabled={page <= 0} onClick={() => onPage(page - 1)}>Anterior</button>
        <span aria-live="polite">Página {page + 1} de {pages}</span>
        <button type="button" className="btn" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>Próxima</button>
      </span>
    </nav>
  );
}
