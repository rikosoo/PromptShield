// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { chatgpt } from "../../src/sites/chatgpt";
import { claude } from "../../src/sites/claude";
import { copilot } from "../../src/sites/copilot";
import { gemini } from "../../src/sites/gemini";
import { enterSubmits } from "../../src/sites/types";

const page = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");

describe("módulos de site (seletores A VERIFICAR contra as páginas reais)", () => {
  it("só casam com o próprio domínio", () => {
    expect(chatgpt.matches("chatgpt.com")).toBe(true);
    expect(chatgpt.matches("chatgpt.com.malicioso.test")).toBe(false);
    expect(claude.matches("claude.ai")).toBe(true);
    expect(claude.matches("claude.ai")).toBe(true);
    expect(claude.matches("chatgpt.com")).toBe(false);
  });
  it("chatgpt: acha campo e botão, com alternativas", () => {
    const d = page('<div id="prompt-textarea" contenteditable="true"></div><button data-testid="send-button"></button>');
    expect(chatgpt.findInput(d)?.id).toBe("prompt-textarea");
    expect(chatgpt.findSend(d)?.getAttribute("data-testid")).toBe("send-button");
    const alt = page('<textarea data-testid="prompt-textarea"></textarea><button aria-label="Send prompt"></button>');
    expect(chatgpt.findInput(alt)?.tagName).toBe("TEXTAREA");
    expect(chatgpt.findSend(alt)).not.toBeNull();
  });
  it("claude: acha campo e botão, com alternativas", () => {
    const d = page('<div contenteditable="true" class="ProseMirror"></div><button aria-label="Send message"></button>');
    expect(claude.findInput(d)).not.toBeNull();
    expect(claude.findSend(d)).not.toBeNull();
  });
  it("quando o site muda, devolve null em vez de errar", () => {
    const d = page("<p>nada aqui</p>");
    expect(chatgpt.findInput(d)).toBeNull();
    expect(claude.findSend(d)).toBeNull();
  });
  it("Enter envia; Shift+Enter, Ctrl+Enter e IME não", () => {
    const k = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);
    expect(enterSubmits(k({ key: "Enter" }))).toBe(true);
    expect(enterSubmits(k({ key: "Enter", shiftKey: true }))).toBe(false);
    expect(enterSubmits(k({ key: "Enter", ctrlKey: true }))).toBe(false);
    expect(enterSubmits(k({ key: "Enter", isComposing: true }))).toBe(false);
    expect(enterSubmits(k({ key: "a" }))).toBe(false);
  });
});

describe("gemini e copilot web (seletores A VERIFICAR contra as páginas reais)", () => {
  it("só casam com o próprio host", () => {
    expect(gemini.matches("gemini.google.com")).toBe(true);
    expect(gemini.matches("google.com")).toBe(false);
    expect(copilot.matches("copilot.microsoft.com")).toBe(true);
    expect(copilot.matches("copilot.com")).toBe(true);
    expect(copilot.matches("github.com")).toBe(false);          // o GitHub Copilot em github.com/copilot não é coberto
    expect(copilot.matches("copilot.microsoft.com.malicioso.test")).toBe(false);
  });
  it("gemini: acha campo e botão", () => {
    const d = page('<rich-textarea><div class="ql-editor" contenteditable="true"></div></rich-textarea><button class="send-button"></button>');
    expect(gemini.findInput(d)).not.toBeNull();
    expect(gemini.findSend(d)).not.toBeNull();
    expect(gemini.findInput(page("<p>x</p>"))).toBeNull();
  });
  it("copilot: acha campo e botão", () => {
    const d = page('<textarea id="userInput"></textarea><button data-testid="submit-button"></button>');
    expect(copilot.findInput(d)?.id).toBe("userInput");
    expect(copilot.findSend(d)).not.toBeNull();
    expect(copilot.findInput(page("<p>x</p>"))).toBeNull();
  });
  it("copilot M365: acha o editor Lexical do HTML real (campo verificado; botão ainda não)", () => {
    const d = page('<span role="textbox" contenteditable="true" id="m365-chat-editor-target-element" data-lexical-editor="true" aria-label="Enviar uma mensagem para o Copilot"><p><br></p></span>');
    expect(copilot.findInput(d)?.id).toBe("m365-chat-editor-target-element");
    expect(copilot.findSend(d)).toBeNull();
    const d2 = page('<button type="button" aria-label="Adicionar e gerenciar fontes"></button><button type="submit" aria-label="Enviar"></button>');
    expect(copilot.findSend(d2)?.getAttribute("type")).toBe("submit");    // não confunde com o botão "+"
  });
});
