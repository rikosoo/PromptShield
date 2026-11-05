import type { AppActivity, DeviceRow } from "./types";

/** Como cada IA do catálogo do sensor é monitorada (espelha packages/adapters/claude_code_hook/.../ias.py). `app` liga a IA ao `source.app` dos eventos. */
export type IaMode = "automatico" | "extensao" | "manual" | "indisponivel";
export const IA_INFO: Record<string, { label: string; mode: IaMode; app?: string }> = {
  chatgpt_web: { label: "ChatGPT (web)", mode: "extensao", app: "chatgpt_web" },
  copilot_web: { label: "Copilot (web)", mode: "extensao", app: "copilot_web" },
  gemini_web: { label: "Gemini (web)", mode: "extensao", app: "gemini_web" },
  claude_code: { label: "Claude Code (CLI)", mode: "automatico", app: "claude_code" },
  codex_cli: { label: "Codex (CLI)", mode: "automatico", app: "codex_cli" },
  github_copilot_cli: { label: "GitHub Copilot CLI", mode: "automatico", app: "github_copilot_cli" },
  claude_web: { label: "Claude (web)", mode: "extensao", app: "claude_web" },
};
export const MODE_LABEL: Record<IaMode, string> = { automatico: "automática", extensao: "extensão do navegador", manual: "configuração manual", indisponivel: "indisponível hoje" };
export const iaLabel = (id: string) => IA_INFO[id]?.label ?? id;

/** O que se sabe de uma IA numa máquina. "capturando" só quando chegou evento de verdade; o resto é honesto sobre o que falta. */
export type IaEvidence = "capturando" | "parou" | "aguardando" | "manual" | "indisponivel";
export const EVIDENCE_LABEL: Record<IaEvidence, string> = {
  capturando: "capturando", parou: "sem eventos há mais de 7 dias", aguardando: "aguardando o primeiro evento", manual: "manual, sem como confirmar", indisponivel: "indisponível hoje",
};

export interface IaState { id: string; label: string; mode: IaMode; evidence: IaEvidence; events7d: number; events30d: number; lastAt: string | null }

export function iaState(d: Pick<DeviceRow, "activity">, id: string): IaState {
  const info = IA_INFO[id] ?? { label: id, mode: "manual" as IaMode };
  const act: AppActivity | undefined = info.app ? d.activity?.[info.app] : undefined;
  let evidence: IaEvidence;
  if (info.mode === "indisponivel") evidence = "indisponivel";
  else if (!info.app) evidence = "manual";
  else if (act && act.events_7d > 0) evidence = "capturando";
  else if (act && act.events_30d > 0) evidence = "parou";
  else evidence = "aguardando";
  return { id, label: info.label, mode: info.mode, evidence, events7d: act?.events_7d ?? 0, events30d: act?.events_30d ?? 0, lastAt: act?.last_at ?? null };
}

/** O sensor só fala com o servidor quando alguém usa uma IA: "sem atividade" NÃO quer dizer que quebrou. */
export type SensorStatus = "ativo" | "quieto" | "inativo" | "nunca" | "revogado";
export const STATUS_LABEL: Record<SensorStatus, string> = {
  ativo: "Ativo (24 h)", quieto: "Sem atividade (1 a 7 dias)", inativo: "Inativo (mais de 7 dias)", nunca: "Nunca enviou", revogado: "Revogado",
};
const DAY = 86_400_000;

export function sensorStatus(d: Pick<DeviceRow, "revoked" | "last_seen_at">, now: Date): SensorStatus {
  if (d.revoked) return "revogado";
  if (!d.last_seen_at) return "nunca";
  const age = now.getTime() - new Date(d.last_seen_at).getTime();
  return age <= DAY ? "ativo" : age <= 7 * DAY ? "quieto" : "inativo";
}

export interface SensorFilter { q: string; ia: string; status: SensorStatus | ""; problem?: ProblemCode | "qualquer" | "" }
export type SensorSort = "hostname" | "recente";

export function filterSensors(devices: DeviceRow[], f: SensorFilter, now: Date, sort: SensorSort = "hostname"): DeviceRow[] {
  const q = f.q.trim().toLowerCase();
  const latest = latestVersion(devices);
  const out = devices.filter((d) =>
    (!f.problem || (f.problem === "qualquer" ? problems(d, now, latest).length > 0 : problems(d, now, latest).some((p) => p.code === f.problem))) &&
    (!q || d.hostname.toLowerCase().includes(q)) &&
    (!f.ia || (d.ias ?? []).includes(f.ia)) &&
    (!f.status || sensorStatus(d, now) === f.status));
  return out.sort(sort === "recente"
    ? (a, b) => (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? "") || a.hostname.localeCompare(b.hostname, "pt-BR")
    : (a, b) => a.hostname.localeCompare(b.hostname, "pt-BR", { numeric: true }));
}

export interface SensorSummary { total: number; ativo: number; quieto: number; inativo: number; nunca: number; revogado: number; semIas: number }

export function summarize(devices: DeviceRow[], now: Date): SensorSummary {
  const s: SensorSummary = { total: 0, ativo: 0, quieto: 0, inativo: 0, nunca: 0, revogado: 0, semIas: 0 };
  for (const d of devices) {
    const st = sensorStatus(d, now);
    s[st] += 1;
    if (st !== "revogado") {
      s.total += 1;
      if (!(d.ias ?? []).length) s.semIas += 1;
    }
  }
  return s;
}

/** Alertas por sensor: o que merece uma olhada. Nenhum deles prova defeito; são pistas honestas. Máquina revogada não tem alerta. */
export type ProblemCode = "nunca" | "inativo" | "extensao" | "versao";
export const PROBLEM_LABEL: Record<ProblemCode, string> = {
  nunca: "Nunca enviou (matriculada há mais de 24 h)", inativo: "Sem atividade há mais de 7 dias", extensao: "Extensão sem nenhum evento", versao: "Sensor desatualizado",
};
export interface Problem { code: ProblemCode; text: string }

/** Compara versões "0.3.1" por segmentos numéricos (partes que não são número valem 0). */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((x) => parseInt(x, 10) || 0);
  const pb = b.split(".").map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

/** Versão mais nova entre os sensores não revogados (referência para "desatualizado"). */
export function latestVersion(devices: Pick<DeviceRow, "revoked" | "client_version">[]): string | null {
  let best: string | null = null;
  for (const d of devices) {
    if (!d.revoked && d.client_version && (best === null || compareVersions(d.client_version, best) > 0)) best = d.client_version;
  }
  return best;
}

const HOUR = 3_600_000;

export function problems(d: DeviceRow, now: Date, latest: string | null): Problem[] {
  if (d.revoked) return [];
  const out: Problem[] = [];
  const st = sensorStatus(d, now);
  const age = now.getTime() - new Date(d.enrolled_at).getTime();
  if (st === "nunca" && age > 24 * HOUR) out.push({ code: "nunca", text: "Matriculada há mais de 24 h e nunca enviou nada: o instalador pode ter falhado ou ninguém usou uma IA ainda." });
  if (st === "inativo") out.push({ code: "inativo", text: "Sem atividade há mais de 7 dias: pode estar de férias, desligada ou com o sensor removido." });
  const silent = (d.ias ?? []).filter((id) => {
    const info = IA_INFO[id];
    return info?.mode === "extensao" && info.app && (d.activity?.[info.app]?.events_30d ?? 0) === 0;
  });
  if (silent.length && age > 3 * 24 * HOUR) {
    out.push({ code: "extensao", text: `Habilitada há mais de 3 dias e sem nenhum evento em 30 dias: ${silent.map(iaLabel).join(", ")}. Falta carregar a extensão no navegador, ou o site mudou.` });
  }
  if (latest && d.client_version && compareVersions(d.client_version, latest) < 0) {
    out.push({ code: "versao", text: `Sensor na versão ${d.client_version}; a mais nova da frota é ${latest}.` });
  }
  return out;
}

export function problemCounts(devices: DeviceRow[], now: Date): { total: number; byCode: Record<ProblemCode, number> } {
  const latest = latestVersion(devices);
  const byCode: Record<ProblemCode, number> = { nunca: 0, inativo: 0, extensao: 0, versao: 0 };
  let total = 0;
  for (const d of devices) {
    const ps = problems(d, now, latest);
    if (ps.length) total += 1;
    for (const p of ps) byCode[p.code] += 1;
  }
  return { total, byCode };
}
