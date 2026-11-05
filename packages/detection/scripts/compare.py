"""Mede o motor em vários conjuntos e imprime/grava as métricas do motor 2.0: exatidão, precisão, recall, taxa de falso positivo e de
falso negativo, latência e cobertura por categoria. Serve para o comparativo ANTES/DEPOIS (rode antes e depois de mudar o motor).

    python packages/detection/scripts/compare.py --out docs/medicoes/antes.json
    python packages/detection/scripts/compare.py --out docs/medicoes/depois.json --versus docs/medicoes/antes.json --markdown docs/motor-2.0-medicao.md

Honestidade: A, B, C, E, G e I guiaram ajustes (medida otimista); D e H nunca guiaram (medida mais honesta). Tudo sintético.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("holdout", Path(__file__).with_name("holdout.py"))
holdout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(holdout)
ev = holdout.ev

SETS = ["holdout_a", "holdout_b", "holdout_c", "holdout_d", "holdout_e", "holdout_f", "holdout_g", "holdout_h", "holdout_i"]
GUIDED = {"holdout_a", "holdout_b", "holdout_c", "holdout_e", "holdout_g", "holdout_i"}
NEUTRAL = holdout.NEUTRAL


def measure(name: str) -> dict:
    rows = ev.load_rows(ROOT / "tests" / "fixtures" / f"{name}.jsonl")
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    lat: list[float] = []
    exact = 0
    neg_total = neg_fp = 0
    for row in rows:
        t0 = time.perf_counter()
        got = set(ev.analyze(ev.to_event(row)).category_ids()) - NEUTRAL
        lat.append((time.perf_counter() - t0) * 1000)
        exp = set(row["expected"]) - NEUTRAL
        exact += got == exp
        if not exp:
            neg_total += 1
            neg_fp += bool(got)
        for c in exp & got:
            counts[c]["tp"] += 1
        for c in got - exp:
            counts[c]["fp"] += 1
        for c in exp - got:
            counts[c]["fn"] += 1
    tp, fp, fn = (sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn"))
    lat.sort()
    return {"rows": len(rows), "exact": exact, "exact_pct": exact / len(rows), "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 1.0, "recall": tp / (tp + fn) if tp + fn else 1.0,
            "false_negative_rate": fn / (tp + fn) if tp + fn else 0.0,
            "false_positive_rate": neg_fp / neg_total if neg_total else 0.0, "negatives": neg_total, "negatives_flagged": neg_fp,
            "latency_ms_p50": round(statistics.median(lat), 2), "latency_ms_p95": round(lat[int(len(lat) * 0.95) - 1], 2),
            "by_category": {k: dict(v) for k, v in sorted(counts.items())}, "guided": name in GUIDED}


def combine(results: dict[str, dict]) -> dict:
    cats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for r in results.values():
        for c, v in r["by_category"].items():
            for k in v:
                cats[c][k] += v[k]
    out = {}
    for c, v in sorted(cats.items()):
        out[c] = {**v, "precision": v["tp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else 1.0,
                  "recall": v["tp"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else 1.0, "covered": v["tp"] > 0}
    return out


def cell(r: dict, b: dict | None, key: str) -> str:
    v = f"{r[key]:.1%}"
    return f"{b[key]:.1%} → {v}" if b else v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--versus")
    ap.add_argument("--markdown")
    a = ap.parse_args()
    results = {n: measure(n) for n in SETS}
    data = {"sets": results, "categories": combine(results)}
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    before = json.loads(Path(a.versus).read_text(encoding="utf-8")) if a.versus else None
    lines = ["| Conjunto | Exatos | Precisão | Recall | Falso negativo | Falso positivo (negativos) | p50 / p95 ms |", "|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        b = before["sets"].get(n) if before else None
        mark = " (guiou ajuste)" if r["guided"] else " (independente)"
        lines.append(f"| {n}{mark} | {cell(r, b, 'exact_pct')} | {cell(r, b, 'precision')} | {cell(r, b, 'recall')} | {cell(r, b, 'false_negative_rate')} | "
                     f"{cell(r, b, 'false_positive_rate')} ({r['negatives_flagged']}/{r['negatives']}) | {r['latency_ms_p50']} / {r['latency_ms_p95']} |")
    cat = ["", "| Categoria | TP | FP | FN | Precisão | Recall | Coberta |", "|---|---|---|---|---|---|---|"]
    for c, v in data["categories"].items():
        bv = before["categories"].get(c) if before else None
        rec = f"{bv['recall']:.0%} → {v['recall']:.0%}" if bv else f"{v['recall']:.0%}"
        pre = f"{bv['precision']:.0%} → {v['precision']:.0%}" if bv else f"{v['precision']:.0%}"
        cat.append(f"| {c} | {v['tp']} | {v['fp']} | {v['fn']} | {pre} | {rec} | {'sim' if v['covered'] else 'NÃO'} |")
    text = "\n".join(lines + cat)
    print(text)
    if a.markdown:
        Path(a.markdown).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
