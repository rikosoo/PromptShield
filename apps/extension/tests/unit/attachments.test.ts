import { describe, expect, it } from "vitest";
import { buildEvent } from "../../src/api";
import { createTracker, infoOf, MAX_FILES } from "../../src/attachments";
import type { FullConfig } from "../../src/types";

const cfg: FullConfig = { apiUrl: "http://x", apiKey: "k", domains: [], failMode: "open", timeoutMs: 1000 };

describe("attachments", () => {
  it("guarda só nome, tamanho e tipo, sem duplicar e com limite", () => {
    const t = createTracker();
    t.add(infoOf([{ name: "a.pdf", size: 1, type: "application/pdf" }, { name: "a.pdf", size: 1, type: "application/pdf" }]));
    expect(t.list()).toEqual([{ name: "a.pdf", size: 1, type: "application/pdf" }]);
    t.add(infoOf(Array.from({ length: 50 }, (_, i) => ({ name: `f${i}`, size: i, type: "" }))));
    expect(t.list()).toHaveLength(MAX_FILES);
    t.clear();
    expect(t.list()).toEqual([]);
    expect(infoOf(null)).toEqual([]);
  });

  it("evento: arquivo sem texto vira file_upload; com texto continua prompt; sem arquivo não manda o campo", () => {
    const f = [{ name: "folha.xlsx", size: 10, type: "" }];
    const only = buildEvent({ app: "chatgpt_web", text: "  ", sessionPath: "/c/1", files: f }, cfg, "i", "u@x.com");
    expect(only.kind).toBe("file_upload");
    expect(only.content.attachments).toEqual([{ name: "folha.xlsx", size: 10, mime: null }]);
    expect(buildEvent({ app: "chatgpt_web", text: "oi", sessionPath: "/c/1", files: f }, cfg, "i", "u@x.com").kind).toBe("prompt");
    expect("attachments" in buildEvent({ app: "a", text: "oi", sessionPath: "" }, cfg, "i", "u@x.com").content).toBe(false);
  });
});
