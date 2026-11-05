"use client";
import { dayLabel } from "@/lib/format";
import type { Overview } from "@/lib/types";

/** Barras de eventos de alto risco por dia. Acessível: descrição em texto e tabela equivalente. */
export function DailyBars({ daily, threshold }: { daily: Overview["daily"]; threshold: number }) {
  const W = 640, H = 190, L = 34, B = 26, T = 10, R = 8;
  const max = Math.max(1, ...daily.map((d) => d.high_risk));
  const step = max <= 4 ? 1 : Math.ceil(max / 4);
  const ticks = Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step);
  const bw = (W - L - R) / daily.length;
  const total = daily.reduce((a, d) => a + d.high_risk, 0);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Eventos de alto risco por dia, últimos ${daily.length} dias: ${total} no total`} className="h-auto w-full">
        {ticks.map((t) => {
          const y = T + (H - T - B) * (1 - t / max);
          return (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y} y2={y} stroke="var(--color-line)" strokeWidth={1} />
              <text x={L - 6} y={y + 4} textAnchor="end" fontSize={11} fill="var(--color-muted)">{t}</text>
            </g>
          );
        })}
        {daily.map((d, i) => {
          const h = ((H - T - B) * d.high_risk) / max;
          const x = L + i * bw + bw * 0.15;
          return (
            <g key={d.date}>
              <rect x={x} y={H - B - h} width={bw * 0.7} height={h} rx={2} fill="var(--color-accent)"><title>{`${dayLabel(d.date)}: ${d.high_risk} de alto risco, ${d.events} eventos`}</title></rect>
              {(daily.length <= 14 || i % 2 === 0) && <text x={x + bw * 0.35} y={H - 8} textAnchor="middle" fontSize={10} fill="var(--color-muted)">{dayLabel(d.date)}</text>}
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-1 text-xs text-muted">Alto risco = score de {threshold} ou mais.</figcaption>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-accent underline">Ver os números em tabela</summary>
        <table className="mt-2 w-full text-left text-sm">
          <caption className="sr-only">Eventos por dia</caption>
          <thead><tr><th scope="col" className="th">Dia</th><th scope="col" className="th">Eventos</th><th scope="col" className="th">Alto risco</th></tr></thead>
          <tbody>{daily.map((d) => <tr key={d.date}><th scope="row" className="td font-normal">{dayLabel(d.date)}</th><td className="td font-mono">{d.events}</td><td className="td font-mono">{d.high_risk}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

/** Uso por ferramenta, separando conta corporativa e conta pessoal (shadow AI). */
export function AppUsage({ rows, label }: { rows: Overview["by_app"]; label: (a: string) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.corporate + r.personal));
  if (!rows.length) return <p className="py-4 text-center text-sm text-muted">Sem dados no período.</p>;
  return (
    <div>
      <ul aria-label="Uso por ferramenta" className="space-y-3">
        {rows.map((r) => (
          <li key={r.app} className="text-sm">
            <div className="mb-1 flex justify-between gap-2"><span className="truncate font-medium">{label(r.app)}</span>
              <span className="font-mono text-xs tabular-nums">{r.corporate} corporativa · {r.personal} pessoal</span></div>
            <div aria-hidden className="flex h-2.5 overflow-hidden rounded-full border border-line bg-panel2" style={{ width: `${((r.corporate + r.personal) / max) * 100}%`, minWidth: "1.5rem" }}>
              <span className="bar-fill block h-full bg-accent" style={{ width: `${(r.corporate / Math.max(1, r.corporate + r.personal)) * 100}%` }} />
              <span className="bar-fill block h-full bg-high" style={{ width: `${(r.personal / Math.max(1, r.corporate + r.personal)) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex gap-4 text-xs text-muted"><span><span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />Conta corporativa</span><span><span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full bg-high" />Conta pessoal</span></p>
    </div>
  );
}


/** Linha pequena de evolução do indicador (0 a 100). Descrição em texto para leitores de tela. */
export function Spark({ series, days, label }: { series: number[]; days: string[]; label: string }) {
  const W = 120, H = 28;
  if (series.length < 2) return null;
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * W},${H - 2 - ((H - 4) * v) / 100}`).join(" ");
  const last = series[series.length - 1];
  const peak = Math.max(...series);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}: de ${dayLabel(days[0])} a ${dayLabel(days[days.length - 1])}, pico ${peak}, último dia ${last}`} className="h-7 w-28">
      <polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} />
    </svg>
  );
}
