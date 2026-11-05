import { describe, expect, it } from "vitest";
import { failurePlan, labelsOf, planFor } from "../../src/decision";
import type { ApiResult } from "../../src/types";

const R = (decision: ApiResult["decision"], extra: Partial<ApiResult> = {}): ApiResult => ({
  event_id: "e", decision, would_decide: decision, masked_text: "***", categories: [{ id: "pii", confidence: 0.97 }, { id: "segredo", confidence: 0.3 }],
  risk: { score: 58 }, ...extra,
});

describe("planFor", () => {
  it("mapeia cada decisão da política para uma ação da interface", () => {
    expect(planFor(R("allow")).kind).toBe("send");
    expect(planFor(R("alert")).kind).toBe("warn");
    expect(planFor(R("mask"))).toMatchObject({ kind: "mask", masked: "***" });
    expect(planFor(R("block")).kind).toBe("block");
    expect(planFor(R("ask_justification")).kind).toBe("justify");
  });
  it("só cita categorias com confiança de pelo menos 0,5", () => {
    expect(labelsOf(R("block"))).toEqual(["dados pessoais"]);
  });
  it("falha da API: fail-open envia, fail-closed bloqueia", () => {
    expect(failurePlan("open").kind).toBe("send");
    expect(failurePlan("closed").kind).toBe("block");
  });
});
