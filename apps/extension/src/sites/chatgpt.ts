import { enterSubmits, firstMatch, type SiteModule } from "./types";

// A VERIFICAR: seletores escritos a partir do conhecimento do site, NÃO conferidos contra a página real
// (chatgpt.com não é acessível do ambiente de desenvolvimento). Integração EXPERIMENTAL.
const INPUT = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', 'textarea[data-testid="prompt-textarea"]'];
const SEND = ['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Enviar prompt"]', "form button[type=submit]"];

export const chatgpt: SiteModule = {
  id: "chatgpt",
  app: "chatgpt_web",
  matches: (h) => h === "chatgpt.com" || h.endsWith(".chatgpt.com"),
  findInput: (doc) => firstMatch(doc, INPUT),
  findSend: (doc) => firstMatch(doc, SEND),
  isSubmitKey: enterSubmits,
};
