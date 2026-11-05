import { describe, expect, it } from "vitest";
import { mutationAllowed, safeApiPath } from "./proxy";

describe("safeApiPath", () => {
  it("aceita só caminhos /v1/...", () => {
    expect(safeApiPath(["v1", "events"])).toBe("v1/events");
    expect(safeApiPath(["v1", "incidents", "3f2a-1"])).toBe("v1/incidents/3f2a-1");
    expect(safeApiPath(["v1", "events", "export.csv"])).toBe("v1/events/export.csv");
  });
  it("recusa tudo o mais, inclusive tentativas de sair do /v1", () => {
    for (const bad of [["dev", "token"], ["v1", "..", "dev", "token"], ["openapi.json"], ["v1", ""], ["v1", "events?x=1"], ["v1", "a b"], [], ["v1", "%2e%2e"], ["v1", "a.b.c"], ["v1", "x.", "y"], ["v1", "..csv"]]) {
      expect(safeApiPath(bad), JSON.stringify(bad)).toBeNull();
    }
  });
});

describe("mutationAllowed (CSRF)", () => {
  const ok = { origin: "https://console.exemplo.test", host: "console.exemplo.test", requestedWith: "promptshield" };
  it("leitura sempre passa", () => expect(mutationAllowed("GET", { origin: null, host: null, requestedWith: null })).toBe(true));
  it("escrita exige cabeçalho próprio e Origin igual ao host", () => {
    expect(mutationAllowed("POST", ok)).toBe(true);
    expect(mutationAllowed("PATCH", { ...ok, requestedWith: null })).toBe(false);
    expect(mutationAllowed("PUT", { ...ok, origin: "https://site-malicioso.test" })).toBe(false);
    expect(mutationAllowed("POST", { ...ok, origin: null })).toBe(false);
    expect(mutationAllowed("POST", { ...ok, origin: "isto-nao-e-url" })).toBe(false);
  });
});
