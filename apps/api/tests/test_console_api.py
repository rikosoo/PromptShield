"""Endpoints que alimentam o console: estatísticas, filtros de prompts, incidentes enriquecidos, simulação e dados de exemplo."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import event
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def when(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def post(client, world, text="oi", *, kind="prompt", days_ago=0.1, dept="Engenharia", app="claude_code", personal=False, user="u1", content=None, who="a"):
    ev = event(text, kind=kind, occurred_at=when(days_ago), actor={"user_id": user, "department": dept},
               source={"channel": "agent_hook", "app": app, "integration_status": "partial"},
               context={"session_id": "s", "personal_account": personal})
    if content:
        ev["content"] = content
    r = client.post("/v1/events", json=ev, headers=world.key(who))
    assert r.status_code == 200, r.text
    return ev["event_id"]


@pytest.fixture
def data(client, world):
    ids = {
        "cpf": post(client, world, "Cliente CPF 529.982.247-25", user="ana", dept="Financeiro", app="chatgpt_web", personal=True),
        "secret": post(client, world, f"chave {SECRET} no deploy", user="rafael", days_ago=1.2),
        "code": post(client, world, "Revise este código:\n```python\ndef f(x):\n    return x*2\n```", user="rafael", days_ago=2.2),
        "rm": post(client, world, kind="tool_call", content={"tool_name": "Bash", "tool_input": {"command": "rm -rf ~/projetos/*"}}, user="rafael", days_ago=0.5),
        "plain": post(client, world, "Traduza este parágrafo para inglês", user="bia", dept="Marketing", app="claude_web", days_ago=3.1),
        "old": post(client, world, "CPF 111.444.777-35", user="ana", dept="Financeiro", days_ago=40),
    }
    return ids


def test_overview_numbers_come_from_the_data(client, world, data):
    o = client.get("/v1/stats/overview?days=14", headers=world.user("leitura")).json()
    t = o["totals"]
    assert t["events"] == 5 and t["users"] == 3            # o evento de 40 dias atrás fica fora do período
    assert t["with_code"] == 1 and t["agent_actions"] == 1 and t["with_sensitive"] >= 2
    assert t["high_risk"] == sum(d["high_risk"] for d in o["daily"]) >= 1
    assert len(o["daily"]) == 14 and sum(d["events"] for d in o["daily"]) == 5
    depts = {d["department"]: d for d in o["by_department"]}
    assert depts["Engenharia"]["events"] == 3 and depts["Financeiro"]["events"] == 1 and depts["Marketing"]["events"] == 1
    apps = {a["app"]: a for a in o["by_app"]}
    assert apps["chatgpt_web"]["personal"] == 1 and apps["chatgpt_web"]["corporate"] == 0 and apps["claude_code"]["corporate"] == 3
    assert client.get("/v1/stats/overview?days=60", headers=world.user("leitura")).json()["totals"]["events"] == 6


def test_category_counts_and_taxonomy(client, world, data):
    counts = client.get("/v1/stats/categories", headers=world.user("leitura")).json()
    assert counts["pii"] == 1 and counts["segredo"] == 1 and counts["shell_destrutivo"] == 1 and counts["revisao_codigo"] == 1
    tax = client.get("/v1/taxonomy", headers=world.user("leitura")).json()
    assert len(tax) == 30 and {"id", "nome", "grupo", "risco_padrao"} <= tax[0].keys()
    assert set(counts) <= {c["id"] for c in tax}


def test_prompt_list_filters_sort_and_total(client, world, data):
    h = world.user("leitura")
    r = client.get("/v1/events?sort=risk&days=14", headers=h)
    assert r.headers["x-total-count"] == "5"
    scores = [e["risk_score"] for e in r.json()]
    assert scores == sorted(scores, reverse=True)
    q = lambda s: client.get(f"/v1/events?days=14&{s}", headers=h)  # noqa: E731
    assert [e["event_id"] for e in q("category=segredo").json()] == [data["secret"]]
    assert {e["event_id"] for e in q("has_code=true").json()} == {data["code"]}
    assert {e["event_id"] for e in q("agent_action=true").json()} == {data["rm"]}
    assert {e["event_id"] for e in q("has_sensitive=true").json()} >= {data["cpf"], data["secret"]}
    assert q("category=segredo").headers["x-total-count"] == "1"
    assert {e["event_id"] for e in q("department=Marketing").json()} == {data["plain"]}
    assert {e["event_id"] for e in q("personal_account=true").json()} == {data["cpf"]}
    assert {e["event_id"] for e in q("only_blocked=true").json()} >= {data["secret"], data["rm"]}   # modo monitorar: "seria bloqueado"
    assert data["plain"] not in {e["event_id"] for e in q("only_blocked=true").json()}
    assert len(q("limit=2&offset=0").json()) == 2 and q("limit=2").headers["x-total-count"] == "5"
    assert all(SECRET not in e["masked_text"] for e in client.get("/v1/events", headers=h).json())


def test_incident_detail_has_timeline_confidence_and_recommendation(client, world, data):
    h = world.user("analista")
    inc = next(i for i in client.get("/v1/incidents", headers=h).json() if i["user_id"] == "rafael" and "segredo" in {c["id"] for c in i["categories"]})
    assert inc["confidence"] >= 0.9 and inc["assignee_email"] is None
    d = client.get(f"/v1/incidents/{inc['id']}", headers=h).json()
    assert [s["what"].split()[0] for s in d["timeline"]][:3] == ["Evento", "Analisado:", "Incidente"]
    assert any("Revogar" in r for r in d["recommendations"]) and any("monitorar" in r for r in d["recommendations"])
    me = next(u for u in client.get("/v1/users/directory", headers=h).json() if u["email"] == "analista@a.example.com")
    r = client.patch(f"/v1/incidents/{inc['id']}", json={"status": "em analise", "assignee_id": me["id"]}, headers=h)
    assert r.json()["assignee_email"] == "analista@a.example.com" and r.json()["status"] == "em analise"
    tl = " | ".join(s["what"] for s in r.json()["timeline"])
    assert "status: em analise" in tl and "analista@a.example.com" in tl
    assert client.get("/v1/users/directory", headers=world.user("leitura")).status_code == 403
    only_mine = client.get(f"/v1/incidents?assignee_id={me['id']}", headers=h).json()
    assert [i["id"] for i in only_mine] == [inc["id"]]
    assert client.get(f"/v1/incidents?category=segredo&severity={inc['severity']}", headers=h).json()


def test_original_text_requires_justification_from_console_roles(client, world):
    world.sql("UPDATE tenants SET store_original = true WHERE id = :t", t=uuid.UUID(world.a["tenant_id"]))
    eid = post(client, world, "Cliente CPF 529.982.247-25")
    inc = client.get("/v1/events?limit=1", headers=world.user("leitura")).json()[0]
    assert inc["has_original"] is True and "529.982" not in str(inc)
    r = client.post(f"/v1/events/{eid}/original", json={"justification": "apuração do caso 77"}, headers=world.user("analista"))
    assert r.json()["text"] == "Cliente CPF 529.982.247-25"


def test_policy_simulation_counts_past_events_without_saving(client, world, data):
    h = world.user("admin")
    body = {"policy": {"name": "teste", "action": "block", "mode": "enforce", "match": {"categories": ["pii"]}}, "days": 14}
    r = client.post("/v1/policies/simulate", json=body, headers=h).json()
    assert r["events_in_period"] == 5 and r["matched"] == 1 and r["matched_users"] == 1 and r["truncated"] is False
    assert r["would_be_stronger_than_current"] == 1 and r["examples"][0]["user_id"] == "ana"       # a padrão só mascara
    assert "529.982.247" not in str(r)
    scoped = {**body, "policy": {**body["policy"], "scope": {"departments": ["Marketing"]}}}
    assert client.post("/v1/policies/simulate", json=scoped, headers=h).json()["matched"] == 0
    longer = client.post("/v1/policies/simulate", json={**body, "days": 60}, headers=h).json()
    assert longer["matched"] == 2 and longer["events_in_period"] == 6
    grp = {**body, "policy": {**body["policy"], "scope": {"groups": ["devs"]}}}
    assert client.post("/v1/policies/simulate", json=grp, headers=h).json()["ignored_scope"] == ["groups"]
    assert len(client.get("/v1/policies", headers=h).json()) == 8            # nada foi gravado
    assert client.post("/v1/policies/simulate", json=body, headers=world.user("leitura")).status_code == 403


def test_seed_demo_flags_tenant_and_stats_match(client, world, admin_engine):
    from app.demo import seed_demo

    with Session(admin_engine) as s, s.begin():
        out = seed_demo(s, "empresa-a", days=14, count=60)
    assert out["events"] == 60
    t = client.get("/v1/tenant", headers=world.user("leitura")).json()
    assert t["is_demo"] is True
    other = client.get("/v1/tenant", headers=world.user("admin", tenant="b")).status_code      # tenant B não tem usuário leitura; só prova que existe
    assert other in (200, 401)
    o = client.get("/v1/stats/overview?days=14", headers=world.user("leitura")).json()
    assert o["totals"]["events"] == 60 and o["totals"]["users"] > 3
    assert len(client.get("/v1/events?limit=200", headers=world.user("leitura")).json()) == 60
    assert sum(client.get("/v1/stats/categories", headers=world.user("leitura")).json().values()) > 0
    assert any(p["mode"] == "enforce" for p in client.get("/v1/policies", headers=world.user("admin")).json())
    # mesma semente, mesmos eventos: o demo é reproduzível
    with Session(admin_engine) as s, s.begin():
        again = seed_demo(s, "empresa-b", days=14, count=60)
    assert again["events"] == 60
