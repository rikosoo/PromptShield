/** Regras do proxy para a API (puras, testadas). O navegador nunca fala direto com a API nem vê o token. */

const ALLOWED = /^v1\/[A-Za-z0-9_\-/]+(\.[A-Za-z0-9]+)?$/;   // uma extensão final permitida (ex.: events/export.csv)

/** Só caminhos /v1/... sem `..`; devolve o caminho seguro ou null. */
export function safeApiPath(segments: string[]): string | null {
  const path = segments.join("/");
  if (!ALLOWED.test(path) || segments.some((s) => s === ".." || s === "." || s === "")) return null;
  return path;
}

/** Proteção contra CSRF: pedidos que alteram dados precisam ter o cabeçalho próprio e Origin igual ao host. */
export function mutationAllowed(method: string, headers: { origin: string | null; host: string | null; requestedWith: string | null }): boolean {
  if (["GET", "HEAD"].includes(method)) return true;
  if (headers.requestedWith !== "promptshield") return false;
  if (!headers.origin || !headers.host) return false;
  try {
    return new URL(headers.origin).host === headers.host;
  } catch {
    return false;
  }
}
