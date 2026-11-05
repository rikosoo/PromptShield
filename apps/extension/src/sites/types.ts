/**
 * Um módulo por site. Se o site mudar o HTML, só o módulo dele quebra.
 * Os seletores são listas ordenadas: o primeiro que existir vence.
 */
export interface SiteModule {
  id: string;
  /** valor do campo `source.app` do evento universal */
  app: string;
  matches(hostname: string): boolean;
  findInput(doc: Document): HTMLElement | null;
  findSend(doc: Document): HTMLElement | null;
  /** o usuário apertou a tecla que envia? (Enter sem Shift e fora de composição por IME) */
  isSubmitKey(e: KeyboardEvent): boolean;
}

export function firstMatch(doc: Document, selectors: string[]): HTMLElement | null {
  for (const s of selectors) {
    const el = doc.querySelector<HTMLElement>(s);
    if (el) return el;
  }
  return null;
}

export const enterSubmits = (e: KeyboardEvent): boolean =>
  e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey && !e.isComposing;
