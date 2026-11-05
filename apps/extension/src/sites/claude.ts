import { enterSubmits, firstMatch, type SiteModule } from "./types";

// A VERIFICAR: seletores escritos a partir do conhecimento do site, NÃO conferidos contra a página real
// (claude.ai responde 403 ao ambiente de desenvolvimento). Integração EXPERIMENTAL.
const INPUT = ['div[contenteditable="true"][data-testid="chat-input"]', 'div.ProseMirror[contenteditable="true"]', 'fieldset div[contenteditable="true"]'];
const SEND = ['button[aria-label="Send message"]', 'button[aria-label="Send Message"]', 'button[aria-label="Enviar mensagem"]', 'fieldset button[type=submit]'];

export const claude: SiteModule = {
  id: "claude",
  app: "claude_web",
  matches: (h) => h === "claude.ai" || h.endsWith(".claude.ai"),
  findInput: (doc) => firstMatch(doc, INPUT),
  findSend: (doc) => firstMatch(doc, SEND),
  isSubmitKey: enterSubmits,
};
