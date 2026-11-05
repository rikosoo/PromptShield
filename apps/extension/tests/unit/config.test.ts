import { describe, expect, it } from "vitest";
import { DEFAULT_DOMAINS, hostMatches, mergeConfig, toPublic } from "../../src/config";

const M = { api_url: "https://api.exemplo.test/", api_key: "ps_a_b" };

describe("hostMatches", () => {
  it("aceita o domínio e subdomínios, nada além", () => {
    expect(hostMatches("claude.ai", ["claude.ai"])).toBe(true);
    expect(hostMatches("www.claude.ai", ["claude.ai"])).toBe(true);
    expect(hostMatches("claude.ai.malicioso.test", ["claude.ai"])).toBe(false);
    expect(hostMatches("meuclaude.ai", ["claude.ai"])).toBe(false);
    expect(hostMatches("CLAUDE.AI", ["claude.ai"])).toBe(true);
  });
});

describe("mergeConfig", () => {
  it("usa domínios embutidos por padrão e remove a barra final da URL", () => {
    const c = mergeConfig(M, undefined, false);
    expect(c.domains).toEqual(DEFAULT_DOMAINS);
    expect(c.apiUrl).toBe("https://api.exemplo.test");
    expect(toPublic(c)).not.toHaveProperty("apiKey");
    expect(JSON.stringify(toPublic(c))).not.toContain("ps_a_b");
    expect(JSON.stringify(toPublic(c))).not.toContain("api.exemplo.test");
  });
  it("a API só restringe domínios, nunca amplia", () => {
    const c = mergeConfig({ ...M, domains: ["chatgpt.com", "claude.ai"] }, { domains: ["claude.ai", "gemini.google.com"] }, false);
    expect(c.domains).toEqual(["claude.ai"]);
  });
  it("produção recusa API em http; desenvolvimento aceita", () => {
    expect(mergeConfig({ ...M, api_url: "http://api.exemplo.test" }, undefined, false).apiUrl).toBe("");
    expect(toPublic(mergeConfig({ ...M, api_url: "http://api.exemplo.test" }, undefined, false)).configured).toBe(false);
    expect(mergeConfig({ ...M, api_url: "http://127.0.0.1:8000" }, undefined, true).apiUrl).toBe("http://127.0.0.1:8000");
  });
  it("modo de falha: política gerenciada vence a API; padrão é open; valor estranho vira open", () => {
    expect(mergeConfig(M, { failure_mode: "closed" }, false).failMode).toBe("closed");
    expect(mergeConfig({ ...M, fail_mode: "open" }, { failure_mode: "closed" }, false).failMode).toBe("open");
    expect(mergeConfig(M, undefined, false).failMode).toBe("open");
    expect(mergeConfig({ ...M, fail_mode: "talvez" }, undefined, false).failMode).toBe("open");
  });
  it("política da empresa: gerenciada vence a da API", () => {
    expect(mergeConfig({ ...M, policy_url: "https://a.test/p" }, { policy_url: "https://b.test/p" }, false).policyUrl).toBe("https://a.test/p");
    expect(mergeConfig(M, { policy_url: "https://b.test/p" }, false).policyUrl).toBe("https://b.test/p");
  });
  it("limita o timeout a uma faixa segura", () => {
    expect(mergeConfig({ ...M, timeout_ms: 1 }, undefined, false).timeoutMs).toBe(500);
    expect(mergeConfig({ ...M, timeout_ms: 999999 }, undefined, false).timeoutMs).toBe(15000);
  });
});
