"""Mede o motor atual nas revisões humanas exportadas do console (Qualidade da detecção > Exportar revisões).

    python packages/detection/scripts/from_feedback.py revisoes.jsonl [--misses]

Limites: o texto exportado já está MASCARADO (CPF vira ***, segredo vira [segredo]), então o motor roda sobre um texto mais pobre que o
original e pode errar onde a produção acertou; e as revisões não são uma amostra aleatória. Use para achar padrões de erro, não como nota."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("holdout", Path(__file__).with_name("holdout.py"))
holdout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(holdout)


def rows_from(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({"id": r["id"], "group": r.get("verdict", "?"), "lang": "pt", "kind": r.get("kind", "prompt"), "text": r.get("text", ""),
                    "expected": r["expected"], "hard_negative": not r["expected"], "requires_ner": False, "has_name": False})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--misses", action="store_true")
    a = ap.parse_args()
    rows = rows_from(a.path)
    counts, misses = holdout.evaluate_risk(rows)
    r = holdout.summarize(rows, counts, misses)
    print(f"{r['rows']} revisões, {r['exact']} exatas ({r['exact'] / max(1, r['rows']):.1%}); precisão {r['micro_precision']:.3f} recall {r['micro_recall']:.3f} F1 {r['micro_f1']:.3f}")
    for cid, c in sorted(counts.items()):
        print(f"  {cid:28s} tp {c['tp']:3d} fp {c['fp']:3d} fn {c['fn']:3d}")
    if a.misses:
        for m in misses:
            print(f"- {m['id']} [{m['group']}] esperado {m['expected']} obtido {m['got']} :: {m['text']}")


if __name__ == "__main__":
    main()
