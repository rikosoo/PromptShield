import { enterSubmits, firstMatch, type SiteModule } from "./types";

// A VERIFICAR: seletores escritos a partir do conhecimento do site, NÃO conferidos contra a página real
// (copilot.microsoft.com não é acessível do ambiente de desenvolvimento). Integração EXPERIMENTAL.
// Cobre só o Microsoft Copilot na web. O GitHub Copilot em github.com/copilot NÃO é coberto (um módulo por host inteiro injetaria em todo o github.com).
// Campo do Copilot (variante M365 "BebopLite"): HTML real colado pelo dono do produto em 2026-11-04: <span role="textbox" contenteditable
// id="m365-chat-editor-target-element" data-lexical-editor="true" aria-label="Enviar uma mensagem para o Copilot">. O botão de enviar NÃO veio
// (só aparece depois de digitar): os seletores dele seguem A VERIFICAR; o Enter já envia sem ele.
const INPUT = ['#m365-chat-editor-target-element', 'span[role="textbox"][data-lexical-editor="true"]', "textarea#userInput", 'textarea[data-testid="composer-input"]', 'textarea[placeholder]', 'div[contenteditable="true"][role="textbox"]'];
// Botão verificado no HTML real (copilot.com/chat, 2026-11-04): <button type="submit" aria-label="Enviar"> (pt-BR; em inglês deve ser "Send"/"Submit": A VERIFICAR).
const SEND = ['button[type="submit"][aria-label="Enviar"]', 'button[type="submit"][aria-label="Send"]', 'button[data-testid="submit-button"]', 'button[aria-label="Submit message"]', 'button[title="Submit message"]', 'button[aria-label="Enviar mensagem"]'];

export const copilot: SiteModule = {
  id: "copilot",
  app: "copilot_web",
  matches: (h) => h === "copilot.microsoft.com" || h === "copilot.com",
  findInput: (doc) => firstMatch(doc, INPUT),
  findSend: (doc) => firstMatch(doc, SEND),
  isSubmitKey: enterSubmits,
};
