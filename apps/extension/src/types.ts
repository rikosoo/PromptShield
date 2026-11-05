/** Erro que a API devolve quando a licença ou o contrato da empresa PAROU a inspeção (cabeçalho X-PromptShield-Inspection: stopped). */
export const INSPECTION_STOPPED = "INSPECAO_PARADA";

export type Decision = "allow" | "mask" | "block" | "ask_justification" | "alert";
export type FailMode = "open" | "closed";

export interface Category {
  id: string;
  confidence: number;
}

/** Subconjunto da resposta de POST /v1/events que a extensão usa. */
export interface ApiResult {
  event_id: string;
  decision: Decision;
  would_decide: Decision;
  masked_text: string;
  categories: Category[];
  risk: { score: number };
}

/** Configuração completa: só existe no service worker (contém a chave de API). */
export interface FullConfig {
  apiUrl: string;
  apiKey: string;
  userId?: string;
  department?: string;
  domains: string[];
  policyUrl?: string;
  failMode: FailMode;
  timeoutMs: number;
}

/** O que o content script recebe: nunca a chave nem a URL da API. */
export interface PublicConfig {
  configured: boolean;
  domains: string[];
  policyUrl?: string;
  failMode: FailMode;
}

export type Request =
  | { type: "getPublicConfig" }
  | { type: "analyze"; app: string; text: string; sessionPath: string; files?: { name: string; size: number; type: string }[] }
  | { type: "justify"; eventId: string; justification: string };

export type Response<T = unknown> = { ok: true; data: T } | { ok: false; error: string };
