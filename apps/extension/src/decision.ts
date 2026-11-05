import type { ApiResult } from "./types";

export const CATEGORY_LABELS: Record<string, string> = {
  pii: "dados pessoais", financeiro: "dados financeiros", saude: "dados de saúde", segredo: "credenciais ou segredos",
  cliente: "base de clientes", rh: "dados de RH", codigo_proprietario: "código proprietário",
  injection_direta: "prompt injection", jailbreak: "jailbreak", extracao_system_prompt: "extração de prompt do sistema",
  estrategia_ma: "estratégia e M&A", juridico: "conteúdo jurídico", propriedade_intelectual: "propriedade intelectual",
};

export type Plan =
  | { kind: "send" }
  | { kind: "warn"; labels: string[] }
  | { kind: "mask"; labels: string[]; masked: string }
  | { kind: "block"; labels: string[] }
  | { kind: "justify"; labels: string[] };

export function labelsOf(r: ApiResult): string[] {
  const out = r.categories.filter((c) => c.confidence >= 0.5).map((c) => CATEGORY_LABELS[c.id] ?? c.id.replace(/_/g, " "));
  return [...new Set(out)];
}

/** Decisão da política -> o que a interface faz. Em modo monitorar a API devolve sempre `allow`. */
export function planFor(r: ApiResult): Plan {
  const labels = labelsOf(r);
  switch (r.decision) {
    case "block": return { kind: "block", labels };
    case "mask": return { kind: "mask", labels, masked: r.masked_text };
    case "ask_justification": return { kind: "justify", labels };
    case "alert": return { kind: "warn", labels };
    default: return { kind: "send" };
  }
}

export function failurePlan(failMode: "open" | "closed"): Plan {
  return failMode === "closed" ? { kind: "block", labels: [] } : { kind: "send" };
}
