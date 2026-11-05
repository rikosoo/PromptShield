"""Análise de prompts: filtros novos, sinais agregados e detalhe com trechos. Dados SINTÉTICOS."""
import pytest
from conftest import event

pytestmark = pytest.mark.db

SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def post(client, world, text, **over):
    r = client.post("/v1/events", json=event(text, **over), headers=world.key())
    assert r.status_code == 200, r.text
    return r.json()


def tool(client, world, name, command):
    ev = event("", kind="tool_call")
    ev["content"] = {"tool_name": name, "tool_input": {"command": command}}
    assert client.post("/v1/events", json=ev, headers=world.key()).status_code == 200


def listing(client, world, **params):
    return client.get("/v1/events", params={"days": 365, **params}, headers=world.user("leitura")).json()


def test_filters_by_kind_text_span_type_and_intent(client, world):
    post(client, world, f"SIMULADO: revise meu deploy, a chave é {SECRET}")
    post(client, world, "SIMULADO: resuma este texto sobre café")
    post(client, world, "SIMULADO: o código é confidencial, queria melhorar")
    tool(client, world, "PowerShell", "Get-Content $HOME\\.aws\\credentials")

    assert {e["kind"] for e in listing(client, world, kind="tool_call")} == {"tool_call"}
    assert len(listing(client, world, kind="prompt")) == 3
    assert len(listing(client, world, q="café")) == 1
    assert len(listing(client, world, q="%%")) == 0                                  # % e _ são literais, não curingas
    assert SECRET not in str(listing(client, world))                                # a busca e a lista só veem texto mascarado
    assert len(listing(client, world, span_type="aws_access_key")) == 1
    assert len(listing(client, world, intent="resumir")) == 1
    assert len(listing(client, world, intent="declara_confidencial")) == 1
    assert len(listing(client, world, intent="revisar_corrigir")) == 1


def test_detail_has_spans_tool_name_and_session_but_no_original(client, world):
    post(client, world, f"SIMULADO: chave {SECRET}")
    tool(client, world, "PowerShell", "Get-Content $HOME\\.aws\\credentials")
    rows = {e["kind"]: e for e in listing(client, world)}
    assert rows["tool_call"]["tool_name"] == "PowerShell" and rows["tool_call"]["masked_text"].startswith("Get-Content")
    assert rows["prompt"]["session_id"] == "s1"
    spans = rows["prompt"]["spans"]
    assert any(sp["type"] == "aws_access_key" for sp in spans) and SECRET not in str(spans)
    assert rows["prompt"]["flags"]["intents"] == []


def test_signals_are_counts_only(client, world):
    post(client, world, f"SIMULADO: chave {SECRET} e outra {SECRET}")
    post(client, world, "SIMULADO: traduza isto")
    tool(client, world, "PowerShell", "ls")
    sg = client.get("/v1/stats/signals", headers=world.user("leitura")).json()
    assert sg["span_types"].get("aws_access_key") == 1                                     # um evento conta uma vez, mesmo com dois trechos
    assert sg["intents"].get("traduzir") == 1 and sg["kinds"] == {"prompt": 2, "tool_call": 1} and sg["tools"] == {"PowerShell": 1}
    assert SECRET not in str(sg)
    other = client.get("/v1/stats/signals", headers=world.tok("admin@b.example.com")).json()
    assert other == {"span_types": {}, "intents": {}, "kinds": {}, "tools": {}}      # isolamento por tenant


def _at(day: str):
    return {"occurred_at": f"{day}T12:00:00Z"}


def test_person_date_and_decision_filters(client, world):
    post(client, world, "SIMULADO: texto da ana", actor={"user_id": "ana@x.example", "department": "Vendas"}, **_at("2026-10-10"))
    post(client, world, "SIMULADO: texto do bruno", actor={"user_id": "bruno@x.example", "department": "Engenharia"}, **_at("2026-10-12"))
    post(client, world, f"SIMULADO: chave {SECRET}", actor={"user_id": "bruno@x.example", "department": "Engenharia"}, **_at("2026-10-14"))
    assert len(listing(client, world, user_q="ANA")) == 1
    assert len(listing(client, world, user_q="x.example")) == 3
    assert len(listing(client, world, user_q="%")) == 0
    assert len(listing(client, world, user_id="bruno@x.example")) == 2
    assert len(listing(client, world, date_from="2026-10-11", date_to="2026-10-12")) == 1
    assert len(listing(client, world, date_from="2026-10-12")) == 2
    assert len(listing(client, world, date_to="2026-10-10")) == 1
    r = client.get("/v1/events", params={"days": 365, "user_q": "bruno", "limit": 1}, headers=world.user("leitura"))
    assert r.headers["X-Total-Count"] == "2" and len(r.json()) == 1
    assert client.get("/v1/events", params={"decision": "explode"}, headers=world.user("leitura")).status_code == 422


def test_people_directory_and_isolation(client, world):
    post(client, world, "SIMULADO: oi", actor={"user_id": "ana@x.example", "department": "Vendas"}, occurred_at=_now())
    post(client, world, f"SIMULADO: chave {SECRET}", actor={"user_id": "bruno@x.example", "department": "Engenharia"}, occurred_at=_now())
    other = event("SIMULADO: outro tenant", actor={"user_id": "zed@b.example"}, occurred_at=_now())
    assert client.post("/v1/events", json=other, headers=world.key("b")).status_code == 200
    rows = client.get("/v1/people", headers=world.user("leitura")).json()
    assert [r["user_id"] for r in rows][0] == "bruno@x.example"                 # maior risco primeiro
    assert {r["user_id"] for r in rows} == {"ana@x.example", "bruno@x.example"}  # zed é de outro tenant
    assert rows[0]["high_risk"] >= 1 and rows[0]["events"] == 1
    assert [r["user_id"] for r in client.get("/v1/people", params={"q": "ana"}, headers=world.user("leitura")).json()] == ["ana@x.example"]
    assert client.get("/v1/people", params={"q": "%"}, headers=world.user("leitura")).json() == []


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_csv_export_roles_audit_and_formula_guard(client, world):
    post(client, world, "=HYPERLINK(\"http://evil\") SIMULADO", actor={"user_id": "+cmd@x.example", "department": "Eng"}, occurred_at=_now())
    post(client, world, "SIMULADO: normal", occurred_at=_now())
    for role in ("leitura", "analista"):
        assert client.get("/v1/events/export.csv", headers=world.user(role)).status_code == 403
    assert client.get("/v1/events/export.csv", headers=world.key()).status_code in (401, 403)
    r = client.get("/v1/events/export.csv", params={"days": 1, "user_q": "x"}, headers=world.user("auditor"))
    assert r.status_code == 200 and r.text.startswith("﻿quando_utc,pessoa")
    assert "'=HYPERLINK" in r.text and "'+cmd@x.example" in r.text
    assert SECRET not in r.text
    assert "attachment" in r.headers["content-disposition"]
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'export.prompts_csv'").scalar() == 1
    assert client.get("/v1/events/export.csv", params={"days": 1}, headers=world.user("admin")).status_code == 200


def test_labels_with_control_characters_become_one_line_and_alert_text_is_escaped(client, world):
    r = client.post("/v1/events", json=event("SIMULADO: oi", actor={"user_id": "x\nINJETADO <!channel> <https://evil.example|clique>", "department": "A\r\nB"}),
                    headers=world.key())
    assert r.status_code == 200
    row = client.get("/v1/events", params={"days": 365}, headers=world.user("leitura")).json()[0]
    assert "\n" not in row["user_id"] and "\r" not in row["department"]
    assert client.post("/v1/events", json=event("x", actor={"user_id": "\n\t"}), headers=world.key()).status_code == 422
    from app.notifier import alert_text, plain
    t = alert_text({"severity": "alto", "title": "t\n<!here>", "user_id": "a<!channel>&b", "department": "d>", "score": 1, "categories": [],
                    "console_link": None, "note": "n"})
    assert "<" not in t.replace("<br>", "") and "&lt;!channel&gt;&amp;b" in t and t.count("\n") == 3
    assert plain("a\x00b\x85c") == "a b c"


def test_attachments_names_are_masked_scored_searchable_and_exported(client, world):
    ev = event("SIMULADO: resuma o arquivo", kind="prompt")
    ev["content"]["attachments"] = [{"name": "C:\\Users\\ana\\folha_pagamento.xlsx", "size": 2048, "mime": "application/vnd.ms-excel"},
                                    {"name": "cliente_529.982.247-25.pdf"}, {"name": "foto.png"}]
    r = client.post("/v1/events", json=ev, headers=world.key())
    assert r.status_code == 200, r.text
    assert {"rh", "pii"} <= {c["id"] for c in r.json()["categories"]} and r.json()["flags"]["has_attachments"] is True
    post(client, world, "SIMULADO: sem arquivo")
    rows = listing(client, world, has_attachment="true")
    assert len(rows) == 1 and len(listing(client, world, has_attachment="false")) == 1
    names = [a["name"] for a in rows[0]["attachments"]]
    assert names == ["folha_pagamento.xlsx", "cliente_***.***.***-25.pdf", "foto.png"]      # sem pasta; CPF no nome mascarado
    assert "529.982" not in str(rows[0]) and rows[0]["attachments"][0]["size"] == 2048
    assert len(listing(client, world, q="folha_pag")) == 1                                    # busca pelo nome do arquivo
    csv = client.get("/v1/events/export.csv", params={"days": 365, "has_attachment": "true"}, headers=world.user("auditor")).text
    assert "folha_pagamento.xlsx" in csv and "529.982" not in csv
    bad = event("x")
    bad["content"]["attachments"] = [{"name": "\n"}]
    assert client.post("/v1/events", json=bad, headers=world.key()).status_code == 422
    only = event("", kind="file_upload")
    only["content"]["attachments"] = [{"name": ".env"}]
    assert client.post("/v1/events", json=only, headers=world.key()).json()["flags"]["has_sensitive"] is True
