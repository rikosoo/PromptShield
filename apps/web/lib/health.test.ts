import { describe, expect, it } from "vitest";
import { collectorHealth, detectionHealth } from "./health";
import type { DeviceRow, QualitySummary } from "./types";

const NOW = new Date("2026-11-03T12:00:00Z");
const ago = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();
const dev = (over: Partial<DeviceRow>): DeviceRow => ({ id: "1", hostname: "NB-01", os: "Windows", client_version: "0.1", tools: [], enrolled_at: ago(500), last_seen_at: ago(1), revoked: false, ias: [], activity: {}, ...over });
const q = (over: Partial<QualitySummary>): QualitySummary => ({
  days: 90, events: 100, reviewed: 40, coverage: 0.4, min_for_estimate: 10, note: "", categories: [],
  verdicts: { correta: 36, falso_positivo: 2, faltou: 2 }, ...over,
});

describe("detectionHealth", () => {
  it("sem dados ou poucas revisões: não inventa taxa", () => {
    expect(detectionHealth(null).level).toBe("unknown");
    const few = detectionHealth(q({ reviewed: 3, verdicts: { correta: 1, falso_positivo: 2, faltou: 0 } }));
    expect(few).toMatchObject({ level: "unknown", falsePositiveRate: null, missedRate: null });
  });
  it("calcula as taxas e os níveis pelas bordas de 10% e 20%", () => {
    expect(detectionHealth(q({})).level).toBe("ok");
    expect(detectionHealth(q({})).falsePositiveRate).toBeCloseTo(0.05);
    expect(detectionHealth(q({ verdicts: { correta: 34, falso_positivo: 6, faltou: 0 } })).level).toBe("warn");
    expect(detectionHealth(q({ verdicts: { correta: 30, falso_positivo: 2, faltou: 8 } })).level).toBe("warn");
    expect(detectionHealth(q({ verdicts: { correta: 30, falso_positivo: 9, faltou: 1 } })).level).toBe("crit");
    expect(detectionHealth(q({ verdicts: { correta: 30, falso_positivo: 1, faltou: 9 } })).missedRate).toBeCloseTo(0.225);
  });
});

describe("collectorHealth", () => {
  const act = (n7: number, n30: number) => ({ chatgpt_web: { events_7d: n7, events_30d: n30, last_at: ago(2) } });
  it("conta capturando, parou e aguardando por IA, ignorando revogadas", () => {
    const h = collectorHealth([
      dev({ id: "a", ias: ["chatgpt_web"], activity: act(3, 5) }),
      dev({ id: "b", ias: ["chatgpt_web"], activity: act(0, 4) }),
      dev({ id: "c", ias: ["chatgpt_web"], activity: {} }),
      dev({ id: "d", ias: ["chatgpt_web"], activity: act(9, 9), revoked: true }),
    ], NOW);
    expect(h.rows).toHaveLength(1);
    expect(h.rows[0]).toMatchObject({ id: "chatgpt_web", enabled: 3, capturing: 1, stopped: 1, waiting: 1, level: "crit" });
    expect(h.level).toBe("crit");
    expect(h.confirmedCoverage).toBeCloseTo(1 / 3);
  });
  it("IA sem como confirmar (ids antigos de desktop) não entra na cobertura e nunca conta como coberta", () => {
    const h = collectorHealth([dev({ ias: ["claude_desktop", "codex_desktop"] })], NOW);
    expect(h.rows).toEqual([]);
    expect(h.level).toBe("unknown");
    expect(h.confirmedCoverage).toBeNull();
  });
  it("tudo capturando é saudável; só aguardando é atenção (não é defeito comprovado)", () => {
    expect(collectorHealth([dev({ ias: ["chatgpt_web"], activity: act(1, 1) })], NOW).level).toBe("ok");
    expect(collectorHealth([dev({ ias: ["chatgpt_web"], activity: {} })], NOW).level).toBe("warn");
  });
  it("resume os sensores", () => {
    const h = collectorHealth([dev({ last_seen_at: ago(1) }), dev({ id: "2", last_seen_at: ago(24 * 9) }), dev({ id: "3", revoked: true })], NOW);
    expect(h.sensors).toMatchObject({ total: 2, ativo: 1, inativo: 1, revogado: 1 });
  });
});
