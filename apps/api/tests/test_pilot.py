"""Etapa 9, piloto: cobertura, taxa de falso positivo por amostragem (com intervalo), tempo até o primeiro alerta, relatório final."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import event

from app import pilot

pytestmark = pytest.mark.db
SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def post(client, world, text, user="u1", dept="Engenharia", who="a", **over):
    ev = event(text, actor={"user_id": user, "department": dept}, **over)
    r = client.post("/v1/events", json=ev, headers=world.key(who))
    assert r.status_code == 200, r.text
    return r.json()


def summary(client, world, role="admin"):
    r = client.get("/v1/pilot/summary", headers=world.user(role))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- estatística ----------
def test_wilson_interval_matches_known_values_and_handles_edges():
    lo, hi = pilot.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = pilot.wilson(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-3)
    lo, hi = pilot.wilson(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-3) and hi == pytest.approx(1.0)
    assert pilot.wilson(0, 0) is None
    lo, hi = pilot.wilson(10, 100)
    assert 0.05 < lo < 0.10 < hi < 0.18                      # n maior, intervalo mais estreito que com n=10


# ---------- configuração e cobertura ----------
def test_config_is_admin_only_and_start_marks_the_day(client, world):
    assert client.put("/v1/pilot/config", json={"expected_users": 5}, headers=world.user("analista")).status_code == 403
    assert client.get("/v1/pilot/summary", headers=world.user("leitura")).status_code == 403
    assert summary(client, world, "auditor")["started_at"] is None
    s = client.put("/v1/pilot/config", json={"expected_users": 5, "pilot_days": 30, "start": True}, headers=world.user("admin")).json()
    assert s["started_at"] and s["day"] == 1 and s["days_remaining"] == 29 and s["coverage"]["expected_users"] == 5
    assert client.put("/v1/pilot/config", json={"expected_users": 0}, headers=world.user("admin")).status_code == 422
    assert client.put("/v1/pilot/config", json={"pilot_days": 400}, headers=world.user("admin")).status_code == 422
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'pilot.config'").scalar() == 1


def test_coverage_counts_distinct_active_users_against_the_expected(client, world):
    client.put("/v1/pilot/config", json={"expected_users": 5, "start": True}, headers=world.user("admin"))
    for u, d in (("a", "RH"), ("b", "RH"), ("c", "Engenharia"), ("d", "Engenharia")):
        post(client, world, "oi", user=u, dept=d)
        post(client, world, "oi de novo", user=u, dept=d)
    post(client, world, "do outro tenant", user="x", who="b")
    c = summary(client, world)["coverage"]
    assert c["active_users"] == 4 and c["expected_users"] == 5 and c["rate"] == 0.8
    assert {x["department"]: x["users"] for x in c["by_department"]} == {"RH": 2, "Engenharia": 2}
    assert c["by_channel"][0]["channel"] == "agent_hook" and c["by_channel"][0]["users"] == 4


def test_events_before_the_pilot_start_do_not_count(client, world):
    post(client, world, "antes", user="antigo")
    world.sql("UPDATE events SET received_at = now() - interval '3 days'")
    client.put("/v1/pilot/config", json={"start": True}, headers=world.user("admin"))
    post(client, world, "depois", user="novo")
    s = summary(client, world)
    assert s["coverage"]["active_users"] == 1 and s["totals"]["events"] == 1


# ---------- amostragem e falso positivo ----------
def test_sample_is_random_among_flagged_events_never_repeats_and_is_role_gated(client, world):
    for i in range(6):
        post(client, world, f"chave {SECRET} {i}", user=f"u{i}")
    for i in range(4):
        post(client, world, f"pergunta inocente {i}", user=f"v{i}")            # score 0: nunca entra na amostra
    assert client.post("/v1/pilot/samples", json={"size": 4}, headers=world.user("auditor")).status_code == 403
    first = client.post("/v1/pilot/samples", json={"size": 4}, headers=world.user("analista")).json()
    assert first["size"] == 4
    second = client.post("/v1/pilot/samples", json={"size": 10}, headers=world.user("admin")).json()
    assert second["size"] == 2                                                  # só restavam 2 sinalizados ainda não amostrados
    assert client.post("/v1/pilot/samples", json={"size": 5}, headers=world.user("admin")).json()["size"] == 0
    rows = world.sql("SELECT e.masked_text, a.risk_score FROM pilot_reviews r JOIN events e ON e.id = r.event_pk JOIN analyses a ON a.event_pk = e.id").all()
    assert len(rows) == 6 and all(x.risk_score >= 35 and "inocente" not in x.masked_text for x in rows)
    assert client.post("/v1/pilot/samples", json={"size": 0}, headers=world.user("admin")).status_code == 422


def test_review_queue_is_masked_and_labels_feed_the_false_positive_rate(client, world):
    for i in range(10):
        post(client, world, f"CPF 529.982.247-25 caso {i}", user=f"u{i}")
    client.post("/v1/pilot/samples", json={"size": 10}, headers=world.user("analista"))
    queue = client.get("/v1/pilot/reviews", headers=world.user("analista")).json()
    assert len(queue) == 10 and all("529.982" not in q["masked_text"] and q["label"] is None for q in queue)
    assert client.get("/v1/pilot/reviews", headers=world.user("auditor")).status_code == 403
    labels = ["falso_positivo"] * 2 + ["verdadeiro_positivo"] * 6 + ["incerto"] * 2
    for q, label in zip(queue, labels, strict=True):
        assert client.patch(f"/v1/pilot/reviews/{q['id']}", json={"label": label}, headers=world.user("analista")).status_code == 200
    assert client.patch(f"/v1/pilot/reviews/{queue[0]['id']}", json={"label": "talvez"}, headers=world.user("analista")).status_code == 422
    assert client.patch(f"/v1/pilot/reviews/{uuid.uuid4()}", json={"label": "incerto"}, headers=world.user("analista")).status_code == 404
    assert client.patch(f"/v1/pilot/reviews/{queue[0]['id']}", json={"label": "incerto"}, headers=world.user("analista")).status_code == 200  # reclassificar vale
    # o incerto não entra na taxa: 2 falsos de 8 decididos = 25%... depois da reclassificação acima, 1 de 7
    fp = summary(client, world)["false_positive"]
    assert fp["reviewed"] == 10 and fp["pending"] == 0 and fp["unsure"] == 3
    assert fp["decided"] == 7 and fp["false_positive"] == 1 and fp["rate"] == round(1 / 7, 4)
    assert fp["small_sample"] is True and fp["ci95"][0] < fp["rate"] < fp["ci95"][1]
    assert "não mede falsos negativos" in fp["scope"]
    assert client.get("/v1/pilot/reviews", headers=world.user("analista")).json() == []                  # nada pendente
    assert len(client.get("/v1/pilot/reviews", params={"pending_only": False}, headers=world.user("analista")).json()) == 10


def test_reviews_are_tenant_scoped(client, world):
    post(client, world, f"chave {SECRET}")
    client.post("/v1/pilot/samples", json={"size": 5}, headers=world.user("admin"))
    rid = client.get("/v1/pilot/reviews", headers=world.user("admin")).json()[0]["id"]
    other = world.user("admin", tenant="b")
    assert client.patch(f"/v1/pilot/reviews/{rid}", json={"label": "falso_positivo"}, headers=other).status_code == 404
    assert client.get("/v1/pilot/reviews", headers=other).json() == []
    assert client.post("/v1/pilot/samples", json={}, headers=other).json()["size"] == 0


# ---------- tempo até o primeiro alerta e modo monitorar ----------
def test_time_to_first_alert_and_monitor_only_flag(client, world):
    client.put("/v1/pilot/config", json={"start": True}, headers=world.user("admin"))
    s = summary(client, world)
    assert s["time_to_first_alert_seconds"] is None and s["first_alert_at"] is None and s["monitor_only"] is True
    post(client, world, "tudo calmo")
    assert summary(client, world)["time_to_first_alert_seconds"] is None
    post(client, world, f"chave {SECRET}")
    s = summary(client, world)
    assert s["first_alert_at"] and 0 <= s["time_to_first_alert_seconds"] < 60 and s["first_incident_at"]
    assert s["totals"]["would_act"] >= 1 and s["totals"]["enforced_decisions"] == 0 and s["monitor_only"] is True

    pols = {p["name"]: p for p in client.get("/v1/policies", headers=world.user("admin")).json()}
    p = pols["Bloquear segredos e chaves"]
    body = {k: p[k] for k in ("name", "description", "enabled", "scope", "match", "action")} | {"mode": "enforce"}
    client.put(f"/v1/policies/{p['id']}", json=body, headers=world.user("admin"))
    post(client, world, f"outra chave {SECRET}", user="u2")
    s = summary(client, world)
    assert s["monitor_only"] is False and s["totals"]["enforced_decisions"] == 1


# ---------- relatório final ----------
def test_pilot_report_numbers_match_the_summary(client, world):
    from pypdf import PdfReader

    client.put("/v1/pilot/config", json={"expected_users": 4, "start": True}, headers=world.user("admin"))
    for i in range(3):
        post(client, world, f"chave {SECRET} {i}", user=f"u{i}", dept="Engenharia")
    client.post("/v1/pilot/samples", json={"size": 3}, headers=world.user("admin"))
    for q, label in zip(client.get("/v1/pilot/reviews", headers=world.user("admin")).json(), ["falso_positivo", "verdadeiro_positivo", "verdadeiro_positivo"], strict=True):
        client.patch(f"/v1/pilot/reviews/{q['id']}", json={"label": label}, headers=world.user("admin"))
    s = summary(client, world)
    today = datetime.now(timezone.utc).date()
    body = {"kind": "piloto", "start": str(today - timedelta(days=1)), "end": str(today)}
    csv = client.post("/v1/reports", json={**body, "format": "csv"}, headers=world.user("auditor"))
    assert csv.status_code == 201, csv.text
    text = client.get(f"/v1/reports/{csv.json()['id']}/download", headers=world.user("auditor")).content.decode("utf-8-sig")
    assert f"cobertura,usuarios_ativos,{s['coverage']['active_users']}" in text and "cobertura,taxa,0.75" in text
    assert f"falso_positivo,rate,{s['false_positive']['rate']}" in text and "falso_positivo,small_sample,True" in text
    assert "metas_sugeridas (a combinar)" in text and "modo,somente_monitorar,True" in text
    assert SECRET not in text
    pdf = client.post("/v1/reports", json={**body, "format": "pdf"}, headers=world.user("analista")).json()
    data = client.get(f"/v1/reports/{pdf['id']}/download", headers=world.user("analista")).content
    out = " ".join("\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages).split())
    assert "Relatório final do piloto" in out and "Metas do piloto (sugeridas, a combinar com o cliente)" in out
    assert "Cobertura de usuários 75.0%" in out and "Taxa de falso positivo 33.3%" in out.replace("(revisada por amostragem) ", "")
    assert "amostra pequena" in out and "não mede o que passou sem ser sinalizado" in out and "Nenhuma decisão foi aplicada: confirmado" in out
    assert client.post("/v1/reports/schedules", json={"kind": "piloto", "format": "pdf", "frequency": "semanal"}, headers=world.user("admin")).status_code == 201
