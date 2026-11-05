import { describe, expect, it } from "vitest";
import { historyHref, INJECTION_CATEGORIES, monthRange, readDrill } from "./drill";

describe("drill", () => {
  it("monta o link só com o que tem valor", () => {
    expect(historyHref({})).toBe("/history");
    expect(historyHref({ days: 14, category: "segredo", has_code: false, app: "" })).toBe("/history?days=14&category=segredo");
    expect(historyHref({ has_sensitive: true, min_score: 50 })).toBe("/history?has_sensitive=true&min_score=50");
  });
  it("mês vira primeiro e último dia (ano bissexto e mês curto)", () => {
    expect(monthRange("2026-11")).toEqual({ date_from: "2026-11-01", date_to: "2026-11-30" });
    expect(monthRange("2028-02")).toEqual({ date_from: "2028-02-01", date_to: "2028-02-29" });
    expect(monthRange("2026-12")).toEqual({ date_from: "2026-12-01", date_to: "2026-12-31" });
  });
  it("lê e valida os filtros da URL; o que não confere é ignorado", () => {
    const f = readDrill(`?days=14&category=${INJECTION_CATEGORIES}&severity=critico&alert_status=novo&has_sensitive=true&min_score=50&date_from=2026-11-01&user=ana&app=chatgpt_web`);
    expect(f).toMatchObject({ days: 14, category: INJECTION_CATEGORIES, severity: "critico", alertStatus: "novo", hasSensitive: true, minScore: 50, dateFrom: "2026-11-01", user: "ana", app: "chatgpt_web" });
    const bad = readDrill("?days=99999&category=DROP TABLE&severity=xx&alert_status=zz&min_score=500&date_from=ontem&has_code=talvez");
    expect(bad).toEqual({ days: undefined, app: undefined, department: undefined, user: undefined, word: undefined, category: undefined, severity: undefined,
      alertStatus: undefined, hasSensitive: undefined, hasCode: undefined, agentAction: undefined, minScore: undefined, dateFrom: undefined, dateTo: undefined });
  });
});
