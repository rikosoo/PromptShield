import type { FailMode, FullConfig, PublicConfig } from "./types";

/** Domínios monitorados por padrão (embutido). O administrador pode restringir pela política gerenciada ou pela API. */
export const DEFAULT_DOMAINS = ["chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com", "copilot.com"];

export interface RemoteConfig {
  domains?: string[];
  policy_url?: string | null;
  failure_mode?: FailMode;
  fetchedAt?: number;
}

type Raw = Record<string, unknown>;

export function hostMatches(hostname: string, domains: string[]): boolean {
  const h = hostname.toLowerCase();
  return domains.some((d) => h === d || h.endsWith("." + d));
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}

function strList(v: unknown): string[] | undefined {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x.length > 0).map((x) => x.toLowerCase()) : undefined;
}

/**
 * Junta política gerenciada (admin da máquina), configuração vinda da API e padrões embutidos.
 * - chave, URL da API e modo de falha: o valor gerenciado vence; sem ele, vale o da API; sem ele, "open".
 * - domínios: a API e a política só podem RESTRINGIR os domínios embutidos/gerenciados (interseção).
 * - build de produção só aceita API em https.
 */
export function mergeConfig(managed: Raw, remote: RemoteConfig | undefined, dev: boolean): FullConfig {
  const base = strList(managed.domains) ?? DEFAULT_DOMAINS;
  const domains = remote?.domains ? base.filter((d) => remote.domains!.some((r) => r === d || d.endsWith("." + r))) : base;
  const apiUrl = (str(managed.api_url) ?? "").replace(/\/+$/, "");
  const httpsOk = apiUrl.startsWith("https://") || (dev && apiUrl.startsWith("http://"));
  const fm = str(managed.fail_mode) ?? remote?.failure_mode;
  const timeout = typeof managed.timeout_ms === "number" ? managed.timeout_ms : 4000;
  return {
    apiUrl: httpsOk ? apiUrl : "",
    apiKey: str(managed.api_key) ?? "",
    userId: str(managed.user_id),
    department: str(managed.department),
    domains,
    policyUrl: str(managed.policy_url) ?? str(remote?.policy_url),
    failMode: fm === "closed" ? "closed" : "open",
    timeoutMs: Math.min(Math.max(timeout, 500), 15000),
  };
}

export function toPublic(c: FullConfig): PublicConfig {
  return { configured: Boolean(c.apiUrl && c.apiKey), domains: c.domains, policyUrl: c.policyUrl, failMode: c.failMode };
}
