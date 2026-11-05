"""Revisão humana da análise: regras, papéis, auditoria, resumo por categoria, exportação e isolamento entre empresas. Dados SINTÉTICOS."""
import json

import pytest
from conftest import event

pytestmark = pytest.mark.db

SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def post(client, world, text, who="a", **over):
    ev = event(text, **over)
    r = client.post("/v1/events", json=ev, headers=world.key(who))
    assert r.status_code == 200, r.text
    return ev["event_id"], r.json()


def review(client, world, eid, role="analista", **body):
    return client.post(f"/v1/events/{eid}/feedback", json=body, headers=world.user(role))


def test_roles_and_validation(client, world):
    eid, res = post(client, world, f"SIMULADO: chave {SECRET}")
    cat = res["categories"][0]["id"]
    for role in ("leitura", "auditor"):
        assert review(client, world, eid, role, verdict="correta").status_code == 403
    assert client.post(f"/v1/events/{eid}/feedback", json={"verdict": "correta"}, headers=world.key()).status_code in (401, 403)
    assert review(client, world, eid, verdict="falso_positivo").status_code == 422                          # precisa dizer qual categoria
    assert review(client, world, eid, verdict="falso_positivo", wrong_categories=["rh"]).status_code == 422  # rh não foi sinalizada
    assert review(client, world, eid, verdict="faltou", missing_categories=[cat]).status_code == 422        # já tinha sido sinalizada
    assert review(client, world, eid, verdict="faltou", missing_categories=["inventada"]).status_code == 422
    assert review(client, world, eid, verdict="faltou").status_code == 422
    assert review(client, world, "00000000-0000-4000-8000-000000000000", verdict="correta").status_code == 404
    assert review(client, world, eid, verdict="correta", note="x" * 501).status_code == 422
    assert review(client, world, eid, verdict="falso_positivo", wrong_categories=[cat], extra=1).status_code == 422


def test_last_review_wins_filter_audit_and_detail(client, world):
    eid, res = post(client, world, f"SIMULADO: chave {SECRET}")
    other, _ = post(client, world, "SIMULADO: resuma este texto sobre café")
    cat = res["categories"][0]["id"]
    assert review(client, world, eid, verdict="falso_positivo", wrong_categories=[cat], note="era exemplo").json()["verdict"] == "falso_positivo"
    ok = review(client, world, eid, "admin", verdict="correta", wrong_categories=[cat])                      # correta ignora categorias enviadas
    assert ok.status_code == 200 and ok.json()["wrong_categories"] == []
    assert review(client, world, other, verdict="faltou", missing_categories=["rh"]).status_code == 200
    d = client.get(f"/v1/events/{eid}", headers=world.user("leitura")).json()
    assert d["feedback"]["verdict"] == "correta"
    rows = lambda **p: client.get("/v1/events", params={"days": 365, **p}, headers=world.user("leitura")).json()  # noqa: E731
    assert [r["event_id"] for r in rows(review="correta")] == [eid]
    assert [r["event_id"] for r in rows(review="faltou")] == [other]
    assert len(rows(review="reviewed")) == 2 and rows(review="pending") == []
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'feedback.set'").scalar() == 3
    assert world.sql("SELECT count(*) FROM event_feedback").scalar() == 2                                    # uma linha por evento


def test_summary_per_category_export_and_isolation(client, world):
    ids = []
    for _ in range(6):
        eid, res = post(client, world, f"SIMULADO: chave {SECRET}")
        ids.append((eid, res["categories"][0]["id"]))
    for n, (eid, cat) in enumerate(ids):
        body = {"verdict": "falso_positivo", "wrong_categories": [cat]} if n == 0 else {"verdict": "correta"}
        assert review(client, world, eid, **body).status_code == 200
    eid_b, _ = post(client, world, f"SIMULADO: chave {SECRET}", who="b")
    assert review(client, world, eid_b, verdict="correta").status_code == 404                                # evento de outra empresa
    s = client.get("/v1/feedback/summary", headers=world.user("auditor")).json()
    assert s["reviewed"] == 6 and s["verdicts"] == {"correta": 5, "falso_positivo": 1, "faltou": 0}
    seg = next(c for c in s["categories"] if c["id"] == ids[0][1])
    assert seg["reviewed"] == 6 and seg["wrong"] == 1 and seg["precision_estimate"] == pytest.approx(0.83, abs=0.01)
    assert client.get("/v1/feedback/summary", headers=world.user("leitura")).status_code == 403
    for role in ("leitura", "analista"):
        assert client.get("/v1/feedback/export.jsonl", headers=world.user(role)).status_code == 403
    r = client.get("/v1/feedback/export.jsonl", headers=world.user("auditor"))
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert len(lines) == 6 and SECRET not in r.text and "era exemplo" not in r.text
    fp = next(x for x in lines if x["verdict"] == "falso_positivo")
    assert fp["expected"] == [c for c in fp["reported"] if c != ids[0][1]] and fp["label_source"] == "revisao_humana"
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'export.feedback_jsonl'").scalar() == 1
    sb = client.get("/v1/feedback/summary", headers=world.user("admin", tenant="b")).json()
    assert sb["reviewed"] == 0
