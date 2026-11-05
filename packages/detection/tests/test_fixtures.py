"""Mede o motor no conjunto sintético. Metas iniciais da Etapa 2 (ajustáveis)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("evaluate", Path(__file__).resolve().parents[1] / "scripts" / "evaluate.py")
evaluate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate)


@pytest.fixture(scope="module")
def results():
    rows = evaluate.load_rows()
    counts, misses = evaluate.evaluate(rows)
    return rows, counts, misses


def test_fixture_size_and_languages(results):
    rows, _, _ = results
    assert len(rows) >= 300
    assert {r["lang"] for r in rows} >= {"pt", "en"}
    assert sum(r["hard_negative"] for r in rows) >= 50


@pytest.mark.parametrize("cat", ["pii", "segredo"])
def test_precision_recall_targets(results, cat):
    _, counts, _ = results
    p, r = evaluate.pr(counts[cat])
    assert p >= 0.95, f"precisão de {cat}: {p}"
    assert r >= 0.90, f"recall de {cat}: {r}"


def test_inline_latency_p95_under_50ms():
    lat = evaluate.latency(n=150)
    assert lat["chars"] == 2000
    assert lat["p95_ms"] < 50, lat


def test_no_real_data_markers_in_fixtures():
    """Só e-mails de domínio de exemplo; sem domínios reais conhecidos."""
    text = (ROOT / "tests" / "fixtures" / "examples.jsonl").read_text(encoding="utf-8")
    emails = set(re.findall(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", text))
    allowed = {"exemplo.com.br", "exemplo.test", "db.exemplo.test", "host-estranho.test", "servidor-desconhecido.test",
               "10.0.0.5"}
    bad = {d for d in emails if not (d in allowed or d.endswith((".test", ".exemplo.com.br")) or d.startswith("10."))}
    assert not bad, bad


def test_fixtures_are_valid_jsonl():
    for line in (ROOT / "tests" / "fixtures" / "examples.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert {"id", "kind", "text", "expected"} <= row.keys()
