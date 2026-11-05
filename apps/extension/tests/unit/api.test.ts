import { afterEach, describe, expect, it, vi } from "vitest";
import { buildEvent, postEvent } from "../../src/api";
import { mergeConfig } from "../../src/config";
import { INSPECTION_STOPPED } from "../../src/types";

const cfg = mergeConfig({ api_url: "https://a.test", api_key: "k", user_id: "fulano", department: "RH" }, undefined, false);

describe("buildEvent", () => {
  it("produz o evento universal, marcando a integração como experimental", () => {
    const ev = buildEvent({ app: "claude_web", text: "olá", sessionPath: "/chat/abc" }, cfg, "install-1", "", new Date("2026-10-14T12:00:00Z"));
    expect(ev).toMatchObject({
      occurred_at: "2026-10-14T12:00:00.000Z", kind: "prompt",
      source: { channel: "browser", app: "claude_web", integration_status: "experimental" },
      actor: { user_id: "fulano", device_id: "install-1", department: "RH" },
      content: { text: "olá" }, context: { session_id: "/chat/abc", personal_account: false },
    });
    expect(ev.event_id).toMatch(/^[0-9a-f-]{36}$/);
  });
  it("prefere o e-mail do perfil do navegador; sem nenhum dos dois, 'desconhecido'", () => {
    expect(buildEvent({ app: "a", text: "t", sessionPath: "" }, cfg, "i", "ana@empresa.example").actor.user_id).toBe("ana@empresa.example");
    const bare = mergeConfig({ api_url: "https://a.test", api_key: "k" }, undefined, false);
    expect(buildEvent({ app: "a", text: "t", sessionPath: "" }, bare, "i", "").actor.user_id).toBe("desconhecido");
  });
  it("cada evento tem id próprio", () => {
    const a = buildEvent({ app: "a", text: "t", sessionPath: "" }, cfg, "i", "");
    const b = buildEvent({ app: "a", text: "t", sessionPath: "" }, cfg, "i", "");
    expect(a.event_id).not.toBe(b.event_id);
  });
});

describe("inspeção parada pela licença ou contrato", () => {
  const event = { event_id: "e" };
  const stub = (status: number, headers: Record<string, string>) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status, headers })));
  afterEach(() => vi.unstubAllGlobals());

  it("403 com o cabeçalho de inspeção parada vira o erro próprio (não 'API respondeu 403')", async () => {
    stub(403, { "X-PromptShield-Inspection": "stopped" });
    await expect(postEvent(cfg, event)).rejects.toThrow(INSPECTION_STOPPED);
    stub(403, { "X-PromptShield-Suspended": "1" });
    await expect(postEvent(cfg, event)).rejects.toThrow(INSPECTION_STOPPED);
  });
  it("outros erros continuam sendo erros comuns", async () => {
    stub(403, {});
    await expect(postEvent(cfg, event)).rejects.toThrow("API respondeu 403");
    stub(500, { "X-PromptShield-Inspection": "ativa" });
    await expect(postEvent(cfg, event)).rejects.toThrow("API respondeu 500");
  });
});
