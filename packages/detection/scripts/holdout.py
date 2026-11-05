"""Mede o motor em um conjunto de avaliação independente (holdout_a / holdout_b) e imprime precisão, recall e divergências.

    python packages/detection/scripts/holdout.py holdout_a [--misses] [--markdown]
"""
from __future__ import annotations

import argparse
import importlib.util
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("evaluate", Path(__file__).with_name("evaluate.py"))
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


NEUTRAL = {"produtividade_legitima"}   # uso legítimo de trabalho: não é risco, fica fora das contas


def evaluate_risk(rows):
    """Como evaluate.py, mas ignora categorias neutras (não são risco) dos dois lados."""
    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    misses = []
    for row in rows:
        got = set(ev.analyze(ev.to_event(row)).category_ids()) - NEUTRAL
        exp = set(row["expected"]) - NEUTRAL
        for c in exp & got:
            counts[c]["tp"] += 1
        for c in got - exp:
            counts[c]["fp"] += 1
        for c in exp - got:
            counts[c]["fn"] += 1
        if got != exp:
            misses.append({"id": row["id"], "group": row["group"], "expected": sorted(exp), "got": sorted(got),
                           "text": (row["text"] or str(row.get("tool_input")))[:100].replace("\n", " ")})
    return counts, misses


def run(name: str):
    rows = ev.load_rows(ROOT / "tests" / "fixtures" / f"{name}.jsonl")
    counts, misses = evaluate_risk(rows)
    return rows, counts, misses


def summarize(rows, counts, misses) -> dict:
    tp = sum(c["tp"] for c in counts.values())
    fp = sum(c["fp"] for c in counts.values())
    fn = sum(c["fn"] for c in counts.values())
    p, r = tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    by_lang = defaultdict(lambda: [0, 0])
    bad = {m["id"] for m in misses}
    for row in rows:
        by_lang[row["lang"]][1] += 1
        by_lang[row["lang"]][0] += row["id"] not in bad
    neg = [r_ for r_ in rows if r_["hard_negative"]]
    neg_ok = sum(1 for r_ in neg if r_["id"] not in bad)
    return {"rows": len(rows), "exact": len(rows) - len(misses), "micro_precision": p, "micro_recall": r, "micro_f1": f1,
            "tp": tp, "fp": fp, "fn": fn, "by_lang": {k: v[0] / v[1] for k, v in by_lang.items()},
            "hard_negatives": len(neg), "hard_negatives_clean": neg_ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--misses", action="store_true")
    args = ap.parse_args()
    rows, counts, misses = run(args.name)
    s = summarize(rows, counts, misses)
    print(f"{args.name}: {s['rows']} exemplos, {s['exact']} exatos ({s['exact'] / s['rows']:.1%}); micro precisão {s['micro_precision']:.3f} "
          f"recall {s['micro_recall']:.3f} F1 {s['micro_f1']:.3f} (tp {s['tp']} fp {s['fp']} fn {s['fn']})")
    print("exatos por idioma:", {k: f"{v:.1%}" for k, v in s["by_lang"].items()},
          f"| negativos difíceis limpos: {s['hard_negatives_clean']}/{s['hard_negatives']}")
    print(f"{'categoria':26s} {'tp':>4s} {'fp':>4s} {'fn':>4s}  prec  rec")
    for cid, c in sorted(counts.items()):
        p, r = ev.pr(c)
        print(f"{cid:26s} {c['tp']:4d} {c['fp']:4d} {c['fn']:4d}  {ev.fmt(p)}  {ev.fmt(r)}")
    if args.misses:
        print(f"\ndivergentes ({len(misses)}):")
        for m in misses:
            print(f"- {m['id']} [{m['group']}] esperado {m['expected']} obtido {m['got']} :: {m['text']}")


if __name__ == "__main__":
    main()
