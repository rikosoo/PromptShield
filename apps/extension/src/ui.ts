/**
 * Interface na página: indicador sempre visível e diálogos de decisão.
 * Tudo dentro de um shadow DOM fechado, sem innerHTML (compatível com Trusted Types e CSP restrita).
 */
import type { Plan } from "./decision";

export type DialogResult =
  | { action: "send" }
  | { action: "send_masked" }
  | { action: "cancel" }
  | { action: "justify"; text: string };

export type IndicatorState = "active" | "inspecting" | "warning";

const CSS = `
:host { all: initial; }
* { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.pill { position: fixed; left: 12px; bottom: 12px; z-index: 2147483646; display: flex; gap: 8px; align-items: center;
  background: #0e2a47; color: #fff; border-radius: 999px; padding: 6px 12px; font-size: 12px; line-height: 1.3;
  box-shadow: 0 2px 8px rgba(0,0,0,.35); max-width: min(480px, calc(100vw - 24px)); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #5fcf8f; flex: none; }
.pill[data-state="inspecting"] .dot { background: #e8c547; }
.pill[data-state="warning"] { background: #7a3b00; }
.pill[data-state="warning"] .dot { background: #ffb15c; }
.pill a { color: #9fd0ff; text-decoration: underline; }
.pill .min { background: transparent; border: 0; color: #fff; padding: 0 4px; font-size: 16px; line-height: 1; margin-left: 4px; }
.pill[data-min="1"] { padding: 6px; gap: 0; }
.pill[data-min="1"] > :not(.dot):not(.min) { display: none; }
.pill[data-min="1"] .min { padding: 0 2px 0 6px; }
.overlay { position: fixed; inset: 0; z-index: 2147483647; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; padding: 16px; }
.dlg { background: #fff; color: #1b2733; border-radius: 10px; width: min(520px, 100%); padding: 20px; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
.dlg h2 { margin: 0 0 8px; font-size: 18px; }
.dlg p { margin: 0 0 12px; font-size: 14px; line-height: 1.5; }
.dlg pre { background: #f2f4f7; border: 1px solid #dde3ea; border-radius: 6px; padding: 10px; font-size: 12px; max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-word; margin: 0 0 12px; }
.dlg label { display: block; font-size: 13px; margin-bottom: 4px; }
.dlg textarea { width: 100%; min-height: 72px; border: 1px solid #98a4b3; border-radius: 6px; padding: 8px; font-size: 14px; margin-bottom: 12px; }
.row { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
button { font-size: 14px; border-radius: 6px; padding: 8px 14px; cursor: pointer; border: 1px solid #98a4b3; background: #fff; color: #1b2733; }
button.primary { background: #0a6ed1; border-color: #0a6ed1; color: #fff; }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, textarea:focus-visible, a:focus-visible { outline: 3px solid #ffbf47; outline-offset: 2px; }
`;

let host: HTMLElement | null = null;
let root: ShadowRoot | null = null;
let pill: HTMLElement | null = null;
let msgEl: HTMLElement | null = null;

export function uiHost(): HTMLElement | null {
  return host;
}

function ensureRoot(): ShadowRoot {
  if (root && host?.isConnected) return root;
  host = document.createElement("promptshield-ui");
  root = host.attachShadow({ mode: __DEV__ ? "open" : "closed" }); // aberto só no build de teste (Playwright não enxerga shadow DOM fechado)
  try {
    const sheet = new CSSStyleSheet(); // folhas construídas não passam por `style-src` da página
    sheet.replaceSync(CSS);
    root.adoptedStyleSheets = [sheet];
  } catch {
    const st = document.createElement("style");
    st.textContent = CSS;
    root.appendChild(st);
  }
  document.documentElement.appendChild(host);
  pill = null;
  return root;
}

export function showIndicator(policyUrl?: string): void {
  const r = ensureRoot();
  if (pill?.isConnected) return;
  pill = document.createElement("div");
  pill.className = "pill";
  pill.setAttribute("role", "status");
  pill.dataset.state = "active";
  const dot = document.createElement("span");
  dot.className = "dot";
  msgEl = document.createElement("span");
  msgEl.textContent = "PromptShield: monitoramento ativo.";
  pill.append(dot, msgEl);
  if (policyUrl && /^https:\/\//.test(policyUrl)) {
    const a = document.createElement("a");
    a.href = policyUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "Política da empresa";
    pill.append(a);
  } else {
    const s = document.createElement("span");
    s.textContent = "Consulte a política de uso de IA da empresa.";
    pill.append(s);
  }
  // Minimizar (não fechar): o aviso de transparência continua visível como um ponto; clicar de novo expande.
  const min = document.createElement("button");
  min.type = "button";
  min.className = "min";
  const sync = () => {
    const m = pill?.dataset.min === "1";
    min.textContent = m ? "+" : "–";
    min.setAttribute("aria-label", m ? "Expandir o aviso do PromptShield" : "Minimizar o aviso do PromptShield");
    min.title = m ? "PromptShield: monitoramento ativo (clique para expandir)" : "Minimizar";
  };
  min.addEventListener("click", () => {
    if (pill) pill.dataset.min = pill.dataset.min === "1" ? "0" : "1";
    sync();
  });
  sync();
  // Clicar fora do aviso também o minimiza (só minimiza: o aviso de transparência nunca some).
  document.addEventListener("click", (e) => {
    if (pill && pill.dataset.min !== "1" && host && !e.composedPath().includes(host)) {
      pill.dataset.min = "1";
      sync();
    }
  }, true);
  pill.append(min);
  r.appendChild(pill);
}

export function setIndicator(state: IndicatorState, text?: string): void {
  if (!pill || !msgEl) return;
  pill.dataset.state = state;
  msgEl.textContent = text ?? (state === "inspecting" ? "PromptShield: verificando o prompt…" : "PromptShield: monitoramento ativo.");
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Partial<HTMLElementTagNameMap[K]> = {}, ...kids: (Node | string)[]) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  n.append(...kids);
  return n;
}

export function showPlan(plan: Plan, reasonIfNoLabels = "A política da empresa não permite este envio agora."): Promise<DialogResult> {
  if (plan.kind === "send") return Promise.resolve({ action: "send" });
  const r = ensureRoot();
  return new Promise((resolve) => {
    const labels = "labels" in plan && plan.labels.length ? plan.labels.join(", ") : "";
    let title = "";
    let body = "";
    const buttons: HTMLButtonElement[] = [];
    let ta: HTMLTextAreaElement | null = null;
    const done = (res: DialogResult) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey, true);
      resolve(res);
    };
    const btn = (text: string, onClick: () => void, primary = false) => {
      const b = el("button", { type: "button", textContent: text });
      if (primary) b.className = "primary";
      b.addEventListener("click", onClick);
      buttons.push(b);
      return b;
    };
    const content: Node[] = [];
    const actions: HTMLButtonElement[] = [];
    if (plan.kind === "warn") {
      title = "Atenção: conteúdo sensível";
      body = `Este prompt contém ${labels || "conteúdo sinalizado pela política"}. A empresa será avisada se você enviar.`;
      actions.push(btn("Cancelar", () => done({ action: "cancel" })), btn("Enviar mesmo assim", () => done({ action: "send" }), true));
    } else if (plan.kind === "mask") {
      title = "Enviar com dados mascarados?";
      body = `Este prompt contém ${labels || "dados sensíveis"}. Para enviar, os trechos serão substituídos por máscaras. Confira a versão que será enviada:`;
      content.push(el("pre", { textContent: plan.masked.slice(0, 1500) }));
      actions.push(btn("Cancelar", () => done({ action: "cancel" })), btn("Enviar versão mascarada", () => done({ action: "send_masked" }), true));
    } else if (plan.kind === "block") {
      title = "Envio bloqueado";
      body = labels ? `A política da empresa bloqueia este prompt porque ele contém ${labels}. Remova esse conteúdo e tente de novo.` : reasonIfNoLabels;
      actions.push(btn("Entendi", () => done({ action: "cancel" }), true));
    } else {
      title = "Justificativa necessária";
      body = `Este prompt contém ${labels || "conteúdo sinalizado"}. Para enviar, explique o motivo. A justificativa fica registrada para a equipe de segurança.`;
      ta = el("textarea", { id: "just", rows: 3 });
      const send = btn("Enviar com justificativa", () => ta && done({ action: "justify", text: ta.value.trim() }), true);
      send.disabled = true;
      ta.addEventListener("input", () => (send.disabled = (ta?.value.trim().length ?? 0) < 10));
      content.push(el("label", { htmlFor: "just", textContent: "Justificativa (mínimo de 10 caracteres)" }), ta);
      actions.push(btn("Cancelar", () => done({ action: "cancel" })), send);
    }
    const h = el("h2", { id: "ps-title", textContent: title });
    const dlg = el("div", { className: "dlg" }, h, el("p", { textContent: body }), ...content, el("div", { className: "row" }, ...actions));
    dlg.setAttribute("role", "dialog");
    dlg.setAttribute("aria-modal", "true");
    dlg.setAttribute("aria-labelledby", "ps-title");
    const overlay = el("div", { className: "overlay" }, dlg);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        done({ action: "cancel" });
      } else if (e.key === "Tab") {
        const focusables: HTMLElement[] = [...(ta ? [ta] : []), ...buttons.filter((b) => !b.disabled)];
        const active = r.activeElement as HTMLElement | null;
        const i = focusables.indexOf(active as HTMLElement);
        const next = e.shiftKey ? focusables[(i <= 0 ? focusables.length : i) - 1] : focusables[(i + 1) % focusables.length];
        if (next) {
          e.preventDefault();
          next.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    r.appendChild(overlay);
    (ta ?? buttons[buttons.length - 1])?.focus();
  });
}
