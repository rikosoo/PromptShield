import uuid

import pytest
from conftest import event

pytestmark = pytest.mark.db


def test_cpf_is_masked_and_categorized_and_monitor_allows(client, world):
    r = client.post("/v1/events", json=event("Cliente CPF 529.982.247-25"), headers=world.key())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pii" in {c["id"] for c in body["categories"]}
    assert body["masked_text"] == "Cliente CPF ***.***.***-25"
    assert "529.982.247" not in r.text
    assert body["decision"] == "allow"            # política nasce em monitor
    assert body["would_decide"] == "mask"         # a decisão hipotética é gravada
    assert body["enforced"] is False
    stored = world.sql("SELECT masked_text, original_ciphertext FROM events").one()
    assert stored.masked_text == "Cliente CPF ***.***.***-25" and stored.original_ciphertext is None


def test_declared_invalid_cpf_is_pii(client, world):
    r = client.post("/v1/events", json=event("meu cpf e 3444353432123 pode ver se vazou dados"), headers=world.key())
    assert "pii" in {c["id"] for c in r.json()["categories"]}
    assert "3444353432123" not in r.json()["masked_text"]


def test_idempotent_by_event_id(client, world):
    ev = event("CPF 529.982.247-25")
    first = client.post("/v1/events", json=ev, headers=world.key()).json()
    again = client.post("/v1/events", json=ev, headers=world.key()).json()
    assert first["duplicate"] is False and again["duplicate"] is True
    assert first["risk"]["score"] == again["risk"]["score"]
    assert world.sql("SELECT count(*) FROM events").scalar() == 1
    assert world.sql("SELECT count(*) FROM analyses").scalar() == 1


def test_enforce_policy_changes_the_returned_decision(client, world):
    pols = {p["name"]: p for p in client.get("/v1/policies", headers=world.user("admin")).json()}
    seg = pols["Bloquear segredos e chaves"]
    assert seg["mode"] == "monitor"
    key_event = event("use AKIAZ7QW4XK2M9PLR3TN no deploy")
    assert client.post("/v1/events", json=key_event, headers=world.key()).json()["decision"] == "allow"
    body = {k: seg[k] for k in ("name", "description", "enabled", "scope", "match", "action")} | {"mode": "enforce"}
    assert client.put(f"/v1/policies/{seg['id']}", json=body, headers=world.user("admin")).json()["version"] == 2
    r = client.post("/v1/events", json=event("use AKIAZ7QW4XK2M9PLR3TN no deploy"), headers=world.key()).json()
    assert r["decision"] == "block" and r["enforced"] is True
    assert "AKIAZ7QW4XK2M9PLR3TN" not in r["masked_text"]


def test_policy_scope_by_department_and_group(client, world):
    scoped = {"name": "só Financeiro", "action": "block", "mode": "enforce", "scope": {"departments": ["Financeiro"]},
              "match": {"categories": ["pii"]}}
    assert client.post("/v1/policies", json=scoped, headers=world.user("admin")).status_code == 201
    eng = client.post("/v1/events", json=event("CPF 529.982.247-25"), headers=world.key()).json()
    assert eng["decision"] == "allow"
    fin = event("CPF 529.982.247-25", actor={"user_id": "u9", "department": "Financeiro"})
    assert client.post("/v1/events", json=fin, headers=world.key()).json()["decision"] == "block"


def test_new_policy_defaults_to_monitor(client, world):
    r = client.post("/v1/policies", json={"name": "n", "action": "block"}, headers=world.user("admin"))
    assert r.status_code == 201 and r.json()["mode"] == "monitor"


def test_high_risk_event_opens_incident_and_analyst_can_triage(client, world):
    r = client.post("/v1/events", json=event(kind="tool_call", content={"tool_name": "Bash", "tool_input": {"command": "rm -rf ~/projetos/*"}}),
                    headers=world.key()).json()
    assert r["incident_id"] and "shell_destrutivo" in {c["id"] for c in r["categories"]}
    inc = client.get("/v1/incidents", headers=world.user("leitura")).json()
    assert len(inc) == 1 and inc[0]["status"] == "aberto"
    iid = inc[0]["id"]
    assert client.patch(f"/v1/incidents/{iid}", json={"status": "resolvido"}, headers=world.user("leitura")).status_code == 403
    assert client.patch(f"/v1/incidents/{iid}", json={"status": "resolvido"}, headers=world.user("analista")).json()["status"] == "resolvido"
    assert any(a["action"] == "incident.update" for a in client.get("/v1/audit-log", headers=world.user("auditor")).json())


def test_auth_failures(client, world):
    assert client.post("/v1/events", json=event("x")).status_code == 401
    assert client.post("/v1/events", json=event("x"), headers={"X-API-Key": "ps_deadbeef_invalida"}).status_code == 401
    assert client.get("/v1/events", headers={"Authorization": "Bearer lixo"}).status_code == 401
    # usuário não pode ingerir; chave não pode ler o console
    assert client.post("/v1/events", json=event("x"), headers=world.user("admin")).status_code == 403
    assert client.get("/v1/events", headers=world.key()).status_code == 403


def test_revoked_key_stops_working_and_only_hash_is_stored(client, world):
    created = client.post("/v1/api-keys", json={"name": "outra"}, headers=world.user("admin")).json()
    full = created["key"]
    assert full.startswith("ps_")
    assert world.sql("SELECT count(*) FROM api_keys WHERE key_hash = :k", k=full).scalar() == 0   # o valor claro não está no banco
    assert not any(full in str(r) for r in world.sql("SELECT * FROM api_keys").fetchall())
    assert client.post("/v1/events", json=event("oi"), headers={"X-API-Key": full}).status_code == 200
    assert client.post(f"/v1/api-keys/{created['id']}/revoke", headers=world.user("admin")).status_code == 200
    assert client.post("/v1/events", json=event("oi"), headers={"X-API-Key": full}).status_code == 401
    assert "key" not in client.get("/v1/api-keys", headers=world.user("admin")).json()[0]


def test_only_admin_edits_policies_and_changes_are_audited(client, world):
    body = {"name": "n", "action": "alert"}
    for role in ("analista", "auditor", "leitura"):
        assert client.post("/v1/policies", json=body, headers=world.user(role)).status_code == 403
    assert client.post("/v1/policies", json=body, headers=world.user("admin")).status_code == 201
    log = client.get("/v1/audit-log", headers=world.user("auditor")).json()
    assert log[0]["action"] == "policy.create" and log[0]["actor"] == "admin@a.example.com"
    assert client.get("/v1/audit-log", headers=world.user("leitura")).status_code == 403


def test_tenant_id_mismatch_is_rejected(client, world):
    ev = event("oi", tenant_id=world.b["tenant_id"])
    assert client.post("/v1/events", json=ev, headers=world.key("a")).status_code == 400


def test_invalid_event_is_422(client, world):
    bad = event("x", kind="banana")
    assert client.post("/v1/events", json=bad, headers=world.key()).status_code == 422
    assert client.post("/v1/events", json={**event("x"), "extra": 1}, headers=world.key()).status_code == 422


def test_original_text_is_off_by_default_and_audited_when_on(client, world):
    ev = event("CPF 529.982.247-25")
    client.post("/v1/events", json=ev, headers=world.key())
    just = {"justification": "investigação do incidente 123"}
    r = client.post(f"/v1/events/{ev['event_id']}/original", json=just, headers=world.user("analista"))
    assert r.status_code == 404                                  # nada guardado por padrão
    world.sql("UPDATE tenants SET store_original = true WHERE id = :t", t=uuid.UUID(world.a["tenant_id"]))
    ev2 = event("CPF 529.982.247-25")
    client.post("/v1/events", json=ev2, headers=world.key())
    assert world.sql("SELECT original_ciphertext FROM events WHERE event_id = :e", e=uuid.UUID(ev2["event_id"])).scalar() is not None
    assert b"529.982" not in world.sql("SELECT original_ciphertext FROM events WHERE event_id = :e", e=uuid.UUID(ev2["event_id"])).scalar()
    u = f"/v1/events/{ev2['event_id']}/original"
    assert client.post(u, json={"justification": "curto"}, headers=world.user("analista")).status_code == 422   # exige justificativa
    assert client.post(u, json=just, headers=world.user("auditor")).status_code == 403
    assert client.post(u, json=just, headers=world.user("leitura")).status_code == 403
    ok = client.post(u, json=just, headers=world.user("analista"))
    assert ok.status_code == 200 and ok.json()["text"] == "CPF 529.982.247-25"
    reads = [a for a in client.get("/v1/audit-log", headers=world.user("auditor")).json() if a["action"] == "event.original_read"]
    assert any(a["detail"]["justification"] == just["justification"] for a in reads)
    # a listagem e o detalhe continuam mascarados
    assert "529.982.247" not in client.get(f"/v1/events/{ev2['event_id']}", headers=world.user("analista")).text


def test_dev_token_endpoint_only_exists_in_mock_mode():
    from app.main import app
    # o módulo foi importado com OIDC_MODE=off (padrão): a rota não é registrada
    assert "/dev/token" not in app.openapi()["paths"]


def test_openapi_is_published(client):
    spec = client.get("/openapi.json").json()
    assert "/v1/events" in spec["paths"] and spec["info"]["title"] == "PromptShield API"
    assert client.get("/docs").status_code == 200


def test_failure_mode_is_configurable_audited_and_readable_by_collectors(client, world):
    assert client.get("/v1/hook-config", headers=world.key()).json() == {"failure_mode": "open"}
    assert client.patch("/v1/tenant", json={"failure_mode": "closed"}, headers=world.user("analista")).status_code == 403
    r = client.patch("/v1/tenant", json={"failure_mode": "closed", "retention_days": 30}, headers=world.user("admin"))
    assert r.json()["failure_mode"] == "closed" and r.json()["retention_days"] == 30
    assert client.get("/v1/hook-config", headers=world.key()).json() == {"failure_mode": "closed"}
    assert client.patch("/v1/tenant", json={"retention_days": 3}, headers=world.user("admin")).status_code == 422
    assert any(a["action"] == "tenant.update" for a in client.get("/v1/audit-log", headers=world.user("auditor")).json())
    assert client.get("/v1/hook-config", headers=world.user("admin")).status_code == 403   # usuários não usam a rota de coletor


def test_extension_config_justification_and_domain_validation(client, world):
    cfg = client.get("/v1/extension-config", headers=world.key()).json()
    assert cfg["domains"] == ["chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com", "copilot.com"] and cfg["policy_url"] is None and cfg["failure_mode"] == "open"
    patch = {"policy_url": "https://intranet.exemplo.test/politica-ia", "monitored_domains": ["ChatGPT.com", "gemini.google.com"]}
    assert client.patch("/v1/tenant", json=patch, headers=world.user("admin")).json()["monitored_domains"] == ["chatgpt.com", "gemini.google.com"]
    assert client.get("/v1/extension-config", headers=world.key()).json()["policy_url"] == patch["policy_url"]
    for bad in ({"monitored_domains": ["https://x.com/a"]}, {"monitored_domains": ["*.com"]}, {"policy_url": "http://inseguro.test"}):
        assert client.patch("/v1/tenant", json=bad, headers=world.user("admin")).status_code == 422
    ev = event("CPF 529.982.247-25")
    client.post("/v1/events", json=ev, headers=world.key())
    u = f"/v1/events/{ev['event_id']}/justification"
    assert client.post(u, json={"justification": "curto"}, headers=world.key()).status_code == 422
    assert client.post(u, json={"justification": "preciso enviar para o cliente"}, headers=world.key()).status_code == 204
    assert client.post(f"/v1/events/{uuid.uuid4()}/justification", json={"justification": "preciso enviar para o cliente"}, headers=world.key()).status_code == 404
    assert client.post(u, json={"justification": "preciso enviar para o cliente"}, headers=world.user("analista")).status_code == 403
    log = client.get("/v1/audit-log", headers=world.user("auditor")).json()
    assert any(a["action"] == "event.justification" and a["detail"]["justification"] == "preciso enviar para o cliente" for a in log)
    assert len(client.get("/v1/audit-log", headers=world.user("auditor")).json()) >= 2


def test_cors_only_for_listed_origins():
    import importlib

    from fastapi.testclient import TestClient

    import app.main as m
    from app.config import settings
    old = settings.cors_allowed_origins
    settings.cors_allowed_origins = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    try:
        c = TestClient(importlib.reload(m).app)
        h = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-api-key,content-type"}
        ok = c.options("/v1/events", headers={**h, "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"})
        assert ok.headers.get("access-control-allow-origin") == "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        assert "x-api-key" in ok.headers.get("access-control-allow-headers", "").lower()
        bad = c.options("/v1/events", headers={**h, "Origin": "https://site-malicioso.test"})
        assert "access-control-allow-origin" not in bad.headers
    finally:
        settings.cors_allowed_origins = old
        importlib.reload(m)


def test_sideload_extension_origin_is_allowed_by_default_and_matches_the_extension_id():
    from pathlib import Path

    from fastapi.testclient import TestClient

    import app.main as m
    from app.config import settings
    ext_id = (Path(__file__).resolve().parents[3] / "apps" / "extension" / "sideload-id.txt").read_text().strip()
    assert settings.sideload_extension_origin == f"chrome-extension://{ext_id}"
    c = TestClient(m.app)
    h = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-api-key,content-type"}
    assert c.options("/v1/events", headers={**h, "Origin": settings.sideload_extension_origin}).headers.get("access-control-allow-origin") == settings.sideload_extension_origin
    assert "access-control-allow-origin" not in c.options("/v1/events", headers={**h, "Origin": "https://site-malicioso.test"}).headers
