/** Leitura e escrita do campo de prompt (textarea ou contenteditable), sem innerHTML. */

export function readText(el: HTMLElement): string {
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) return el.value;
  return el.innerText ?? el.textContent ?? "";
}

export function writeText(el: HTMLElement, text: string): void {
  el.focus();
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, text); // passa pelo setter nativo para o React notar
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  // contenteditable (ProseMirror e similares): inserir como o navegador faz na digitação
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  sel?.removeAllRanges();
  sel?.addRange(range);
  const ok = document.execCommand("insertText", false, text);
  if (!ok || readText(el).trim() !== text.trim()) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
  }
}
