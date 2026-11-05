/** Links do painel para a lista de prompts já filtrada ("clicou no número, vê os prompts que o formam"). */
export type DrillValue = string | number | boolean | undefined;

export const INJECTION_CATEGORIES = "injection_direta,injection_indireta,jailbreak,extracao_system_prompt";

export function historyHref(params: Record<string, DrillValue>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "" && v !== false) sp.set(k, String(v));
  const q = sp.toString();
  return q ? `/history?${q}` : "/history";
}

/** "2026-11" -> primeiro e último dia do mês (UTC), para abrir os prompts daquele mês. */
export function monthRange(month: string): { date_from: string; date_to: string } {
  const [y, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { date_from: `${y}-${mm}-01`, date_to: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

const SEV = new Set(["baixo", "medio", "alto", "critico"]);
const STATUS = new Set(["sem_alerta", "novo", "em_analise", "falso_positivo", "resolvido"]);
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Lê e valida os filtros vindos da URL (nunca confia: o que não confere é ignorado). */
export interface DrillFilters {
  days?: number; app?: string; category?: string; severity?: string; alertStatus?: string; department?: string; user?: string; word?: string;
  hasSensitive?: boolean; hasCode?: boolean; agentAction?: boolean; minScore?: number; dateFrom?: string; dateTo?: string;
}
export function readDrill(search: string): DrillFilters {
  const sp = new URLSearchParams(search);
  const text = (k: string, max = 100) => { const v = sp.get(k); return v && v.length <= max ? v : undefined; };
  const int = (k: string, lo: number, hi: number) => { const v = Number(sp.get(k)); return sp.get(k) !== null && Number.isInteger(v) && v >= lo && v <= hi ? v : undefined; };
  const sev = sp.get("severity");
  const st = sp.get("alert_status");
  const cat = sp.get("category");
  const from = sp.get("date_from");
  const to = sp.get("date_to");
  return {
    days: int("days", 1, 365), app: text("app", 40), department: text("department"), user: text("user"), word: text("q"),
    category: cat && /^[a-z_,]{1,300}$/.test(cat) ? cat : undefined, severity: sev && SEV.has(sev) ? sev : undefined, alertStatus: st && STATUS.has(st) ? st : undefined,
    hasSensitive: sp.get("has_sensitive") === "true" || undefined, hasCode: sp.get("has_code") === "true" || undefined, agentAction: sp.get("agent_action") === "true" || undefined,
    minScore: int("min_score", 1, 100), dateFrom: from && DAY.test(from) ? from : undefined, dateTo: to && DAY.test(to) ? to : undefined,
  };
}
