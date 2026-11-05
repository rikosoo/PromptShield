import { enterSubmits, firstMatch, type SiteModule } from "./types";

// A VERIFICAR: seletores escritos a partir do conhecimento do site, NÃO conferidos contra a página real
// (gemini.google.com não é acessível do ambiente de desenvolvimento). Integração EXPERIMENTAL.
const INPUT = ['rich-textarea .ql-editor[contenteditable="true"]', 'div.ql-editor[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]'];
const SEND = ["button.send-button", 'button[aria-label="Send message"]', 'button[aria-label="Enviar mensagem"]', 'button[mattooltip="Send message"]'];

export const gemini: SiteModule = {
  id: "gemini",
  app: "gemini_web",
  matches: (h) => h === "gemini.google.com",
  findInput: (doc) => firstMatch(doc, INPUT),
  findSend: (doc) => firstMatch(doc, SEND),
  isSubmitKey: enterSubmits,
};
