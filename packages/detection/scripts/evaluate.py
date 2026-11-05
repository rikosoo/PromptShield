"""Mede precisão e recall por categoria no conjunto sintético e a latência. Uso:
    python packages/detection/scripts/evaluate.py [--report docs/relatorio-etapa2.md]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import statistics
import time
from collections import defaultdict
from pathlib import Path

from promptshield_detection import analyze
from promptshield_detection.taxonomy import load

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "examples.jsonl"  # --fixtures troca o conjunto (holdout_a, holdout_b)


def to_event(row: dict) -> dict:
    content = {"text": row["text"]}
    if row.get("tool_name"):
        content["tool_name"] = row["tool_name"]
    if row.get("tool_input"):
        content["tool_input"] = row["tool_input"]
    return {"kind": row["kind"], "content": content, "context": {"personal_account": False}}


def _synth():
    spec = importlib.util.spec_from_file_location("synth", FIXTURES.with_name("synth.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render


def load_rows(path: Path | None = None) -> list[dict]:
    """Carrega o JSONL e expande os marcadores de segredos sintéticos (ver tests/fixtures/synth.py)."""
    render = _synth()
    rows = [json.loads(line) for line in (path or FIXTURES).read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row["text"] = render(row["text"])
        if row.get("tool_input"):
            row["tool_input"] = {k: render(v) if isinstance(v, str) else v for k, v in row["tool_input"].items()}
    return rows


def evaluate(rows: list[dict], ner=None) -> tuple[dict[str, dict[str, int]], list[dict]]:
    """Com `ner`, exemplos que contêm nome de pessoa passam a esperar `pii` (nome é dado pessoal).
    Sem `ner`, exemplos que dependem de NER ficam de fora."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    misses = []
    for row in rows:
        if row.get("requires_ner") and ner is None:
            continue
        got = analyze(to_event(row), ner=ner).category_ids()
        exp = set(row["expected"])
        if ner is not None and row.get("has_name"):
            exp.add("pii")
        for c in exp & got:
            counts[c]["tp"] += 1
        for c in got - exp:
            counts[c]["fp"] += 1
        for c in exp - got:
            counts[c]["fn"] += 1
        if got != exp:
            misses.append({"id": row["id"], "group": row["group"], "expected": sorted(exp), "got": sorted(got),
                           "text": (row["text"] or json.dumps(row.get("tool_input")))[:90].replace("\n", " ")})
    return counts, misses


def pr(c: dict[str, int]) -> tuple[float | None, float | None]:
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    return p, r


def latency(n: int = 300, ner=None) -> dict[str, float]:
    base = ("Preciso revisar o contrato do cliente Joao, CPF 529.982.247-25, e-mail joao@exemplo.com.br. "
            "A chave AKIAZ7QW4XK2M9PLR3TN está no .env. SELECT nome FROM clientes WHERE ativo = 1. ")
    text = (base * 20)[:2000]
    ev = {"kind": "prompt", "content": {"text": text}}
    for _ in range(20):
        analyze(ev, ner=ner)
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        analyze(ev, ner=ner)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {"n": n, "chars": len(text), "p50_ms": statistics.median(times),
            "p95_ms": times[int(0.95 * n) - 1], "p99_ms": times[int(0.99 * n) - 1], "max_ms": times[-1]}


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "n/d"


def fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def build_report(rows, counts, misses, lat) -> str:
    cats = load()
    lines = ["# Relatório da Etapa 2: motor de detecção", "",
             f"Conjunto: `tests/fixtures/examples.jsonl`, {len(rows)} exemplos sintéticos "
             f"({sum(1 for r in rows if r['hard_negative'])} negativos difíceis), português e inglês.", "",
             "**Aviso de validade.** O conjunto e o motor foram escritos pela mesma autoria. Os números abaixo medem "
             "consistência com o gabarito sintético, não desempenho em dados reais. Esperam-se piores resultados em produção, "
             "principalmente nas categorias de negócio (dicionários).", "",
             "| Categoria | Grupo | TP | FP | FN | Precisão | Recall |", "|---|---|---|---|---|---|---|"]
    for cid, cat in cats.items():
        c = counts.get(cid, {"tp": 0, "fp": 0, "fn": 0})
        p, r = pr(c)
        lines.append(f"| {cid} | {cat.grupo} | {c['tp']} | {c['fp']} | {c['fn']} | {fmt(p)} | {fmt(r)} |")
    lines += ["", "## Latência (inline, sem classificador de injection)", "",
              f"Texto de {lat['chars']} caracteres, {lat['n']} execuções, Python {platform.python_version()}, "
              f"{platform.system()} {platform.machine()}, CPU: {cpu_name()}, {os.cpu_count()} núcleos (ambiente de nuvem compartilhado).", "",
              f"p50 {lat['p50_ms']:.2f} ms, p95 {lat['p95_ms']:.2f} ms, p99 {lat['p99_ms']:.2f} ms, máx {lat['max_ms']:.2f} ms. Meta: p95 < 50 ms.", "",
              f"## Exemplos divergentes ({len(misses)})", "", "| id | grupo | esperado | obtido | texto |", "|---|---|---|---|---|"]
    for m in misses:
        lines.append(f"| {m['id']} | {m['group']} | {', '.join(m['expected']) or '—'} | {', '.join(m['got']) or '—'} | `{m['text'].replace('|', '/')}` |")
    return "\n".join(lines) + "\n"


def build_ner_section(rows, counts, misses, lat) -> str:
    p, r = pr(counts["pii"])
    lines = ["", "## Com NER local (Presidio + spaCy `pt_core_news_sm` e `en_core_web_sm`)", "",
             f"Exemplos que contêm nome de pessoa passam a esperar `pii` ({sum(1 for x in rows if x.get('has_name'))} exemplos); "
             f"{sum(1 for x in rows if x.get('requires_ner'))} exemplos só existem neste modo.", "",
             f"`pii`: precisão {fmt(p)}, recall {fmt(r)} ({counts['pii']}).", "",
             f"Latência com NER: p50 {lat['p50_ms']:.2f} ms, p95 {lat['p95_ms']:.2f} ms, p99 {lat['p99_ms']:.2f} ms.", "",
             f"Divergentes com NER ({len(misses)}):", ""]
    for m in misses:
        lines.append(f"- {m['id']} ({m['group']}): esperado {', '.join(m['expected']) or '—'}, obtido {', '.join(m['got']) or '—'}: `{m['text'].replace('|', '/')}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    args = ap.parse_args()
    rows = load_rows()
    counts, misses = evaluate(rows)
    lat = latency()
    try:
        from promptshield_detection.ner import NerDetector
        ner = NerDetector()
        ncounts, nmisses = evaluate(rows, ner)
        nlat = latency(ner=ner)
    except Exception as exc:  # NER é opcional
        print("NER indisponível:", exc)
        ner = ncounts = nmisses = nlat = None
    for cid in ("pii", "segredo", "financeiro"):
        p, r = pr(counts[cid])
        print(f"{cid}: precisão {fmt(p)} recall {fmt(r)} {counts[cid]}")
    print("latência:", {k: round(v, 2) for k, v in lat.items()})
    print("divergentes:", len(misses), "de", len(rows))
    if ner is not None:
        p, r = pr(ncounts["pii"])
        print(f"com NER: pii precisão {fmt(p)} recall {fmt(r)} {ncounts['pii']}; divergentes {len(nmisses)}")
        print("latência com NER:", {k: round(v, 2) for k, v in nlat.items()})
    if args.report:
        text = build_report(rows, counts, misses, lat)
        if ner is not None:
            text += build_ner_section(rows, ncounts, nmisses, nlat)
        Path(args.report).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
