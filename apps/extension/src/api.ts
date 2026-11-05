import { INSPECTION_STOPPED, type ApiResult, type FullConfig } from "./types";

export interface PromptInput {
  app: string;
  text: string;
  sessionPath: string;
  files?: { name: string; size: number; type: string }[];
}

export function buildEvent(input: PromptInput, cfg: FullConfig, installId: string, profileEmail: string, now = new Date()) {
  const actor: Record<string, unknown> = { user_id: profileEmail || cfg.userId || "desconhecido", device_id: installId };
  if (cfg.department) actor.department = cfg.department;
  return {
    event_id: crypto.randomUUID(),
    occurred_at: now.toISOString(),
    // integração por extensão: EXPERIMENTAL (seletores dos sites não verificados contra as páginas reais)
    source: { channel: "browser", app: input.app, integration_status: "experimental" },
    actor,
    kind: input.text.trim() || !input.files?.length ? "prompt" : "file_upload",
    // arquivos: só nome, tamanho e tipo. O conteúdo do arquivo nunca é lido pela extensão.
    content: { text: input.text, ...(input.files?.length ? { attachments: input.files.map((f) => ({ name: f.name, size: f.size, mime: f.type || null })) } : {}) },
    // a extensão não sabe se a conta do site é pessoal ou corporativa
    context: { session_id: input.sessionPath.slice(0, 200) || null, personal_account: false },
  };
}

async function call<T>(cfg: FullConfig, method: string, path: string, body?: unknown, expectJson = true): Promise<T> {
  if (!cfg.apiUrl || !cfg.apiKey) throw new Error("extensão sem configuração (api_url e api_key)");
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), cfg.timeoutMs);
  try {
    const r = await fetch(cfg.apiUrl + path, {
      method,
      signal: ctl.signal,
      headers: { "X-API-Key": cfg.apiKey, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      // a empresa/licença parou a inspeção de propósito: a extensão avisa a pessoa e NÃO trata como erro de rede
      if (r.headers.get("X-PromptShield-Inspection") === "stopped" || r.headers.get("X-PromptShield-Suspended")) throw new Error(INSPECTION_STOPPED);
      throw new Error(`API respondeu ${r.status}`);
    }
    return (expectJson ? await r.json() : undefined) as T;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw new Error("tempo esgotado ao consultar a API");
    throw e instanceof Error ? e : new Error(String(e));
  } finally {
    clearTimeout(timer);
  }
}

export const postEvent = (cfg: FullConfig, event: unknown) => call<ApiResult>(cfg, "POST", "/v1/events", event);
export const postJustification = (cfg: FullConfig, eventId: string, justification: string) =>
  call<void>(cfg, "POST", `/v1/events/${eventId}/justification`, { justification }, false);
export const getRemoteConfig = (cfg: FullConfig) =>
  call<{ failure_mode: "open" | "closed"; domains: string[]; policy_url: string | null }>(cfg, "GET", "/v1/extension-config");
