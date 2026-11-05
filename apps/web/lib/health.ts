import { IA_INFO, iaLabel, iaState, summarize, type SensorSummary } from "./sensors";
import type { DeviceRow, QualitySummary } from "./types";

/**
 * Confiabilidade do próprio painel: evita a falsa sensação de segurança.
 * Dois números que o painel de risco sozinho não mostra:
 *  1. a análise erra? (falso positivo e "faltou pegar", segundo revisão humana);
 *  2. os coletores estão de fato entregando eventos?
 * Tudo vem de dados que a API já devolve; nada aqui inventa medida.
 */
export type HealthLevel = "ok" | "warn" | "crit" | "unknown";

export interface DetectionHealth {
  level: HealthLevel;
  reviewed: number;
  reviewCoverage: number;
  /** null enquanto houver poucas revisões para uma taxa que não engane. */
  falsePositiveRate: number | null;
  missedRate: number | null;
  note: string;
}

/** Abaixo disso a taxa não é mostrada como número (mesmo mínimo que a API usa por categoria). */
export function detectionHealth(q: QualitySummary | null | undefined): DetectionHealth {
  if (!q) return { level: "unknown", reviewed: 0, reviewCoverage: 0, falsePositiveRate: null, missedRate: null, note: "Sem dados de revisão." };
  const min = q.min_for_estimate;
  const base = { reviewed: q.reviewed, reviewCoverage: q.coverage };
  if (q.reviewed < min) {
    return { ...base, level: "unknown", falsePositiveRate: null, missedRate: null, note: `Só ${q.reviewed} revisão(ões); são necessárias ${min} para estimar. Revise prompts em "Todos os prompts".` };
  }
  const fp = q.verdicts.falso_positivo / q.reviewed;
  const missed = q.verdicts.faltou / q.reviewed;
  const level: HealthLevel = fp > 0.2 || missed > 0.2 ? "crit" : fp > 0.1 || missed > 0.1 ? "warn" : "ok";
  return { ...base, level, falsePositiveRate: fp, missedRate: missed, note: "Revisões não são amostra aleatória: indicação, não medida." };
}

export interface CollectorRow {
  id: string;
  label: string;
  /** máquinas (não revogadas) com esta IA habilitada */
  enabled: number;
  capturing: number;
  stopped: number;
  waiting: number;
  level: HealthLevel;
}

export interface CollectorHealth {
  level: HealthLevel;
  sensors: SensorSummary;
  rows: CollectorRow[];
  /** 0..1: das combinações máquina+IA que dá para confirmar, quantas chegaram evento nos últimos 7 dias; null se nada a confirmar. */
  confirmedCoverage: number | null;
  note: string;
}

/**
 * Só IAs com `app` (que geram evento) entram na cobertura. Manual e indisponível
 * não têm como ser confirmadas e nunca contam como cobertas.
 * Atenção: sensor só fala quando alguém usa a IA; "aguardando" não é defeito.
 */
export function collectorHealth(devices: DeviceRow[], now: Date): CollectorHealth {
  const active = devices.filter((d) => !d.revoked);
  const rows: CollectorRow[] = [];
  for (const [id, info] of Object.entries(IA_INFO)) {
    if (!info.app) continue;
    const row: CollectorRow = { id, label: iaLabel(id), enabled: 0, capturing: 0, stopped: 0, waiting: 0, level: "unknown" };
    for (const d of active) {
      if (!(d.ias ?? []).includes(id)) continue;
      row.enabled += 1;
      const ev = iaState(d, id).evidence;
      if (ev === "capturando") row.capturing += 1;
      else if (ev === "parou") row.stopped += 1;
      else row.waiting += 1;
    }
    if (row.enabled === 0) continue;
    row.level = row.stopped > 0 ? "crit" : row.capturing === 0 ? "warn" : row.waiting > 0 ? "warn" : "ok";
    rows.push(row);
  }
  rows.sort((a, b) => b.stopped - a.stopped || b.waiting - a.waiting || a.label.localeCompare(b.label, "pt-BR"));
  const enabled = rows.reduce((n, r) => n + r.enabled, 0);
  const capturing = rows.reduce((n, r) => n + r.capturing, 0);
  const sensors = summarize(devices, now);
  const level: HealthLevel = !rows.length ? "unknown" : rows.some((r) => r.level === "crit") ? "crit" : rows.some((r) => r.level === "warn") ? "warn" : "ok";
  return {
    level, sensors, rows,
    confirmedCoverage: enabled ? capturing / enabled : null,
    note: "Um coletor sem eventos não prova defeito (o sensor só fala quando alguém usa a IA), mas \"parou\" (já enviou antes e sumiu) merece investigação.",
  };
}

export const LEVEL_LABEL: Record<HealthLevel, string> = { ok: "Saudável", warn: "Atenção", crit: "Investigar", unknown: "Sem dados suficientes" };
