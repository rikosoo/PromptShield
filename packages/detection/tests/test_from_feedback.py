import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("from_feedback", Path(__file__).resolve().parents[1] / "scripts" / "from_feedback.py")
ff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ff)


def test_rows_from_export_and_measure(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in [
        {"id": "1", "kind": "prompt", "text": "meu cpf é 529.982.247-25", "verdict": "correta", "expected": ["pii"]},
        {"id": "2", "kind": "prompt", "text": "resuma este texto", "verdict": "falso_positivo", "expected": []},
        {"id": "3", "kind": "prompt", "text": "o diagrama interno de rede", "verdict": "faltou", "expected": ["arquitetura"]},
    ]) + "\n", encoding="utf-8")
    rows = ff.rows_from(f)
    assert [r["hard_negative"] for r in rows] == [False, True, False]
    counts, misses = ff.holdout.evaluate_risk(rows)
    assert counts["pii"]["tp"] == 1 and {m["id"] for m in misses} == {"3"}
