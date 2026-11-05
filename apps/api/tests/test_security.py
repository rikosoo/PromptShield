"""Etapa 9, segurança: controle de acesso rota a rota, limite de requisições, rotação de chaves, logs sem conteúdo, métricas."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import event

from app import metrics, ratelimit
from app.config import settings
from app.logging_config import JsonFormatter

pytestmark = [pytest.mark.db, pytest.mark.security]

ALL = ("admin", "analista", "auditor", "leitura")
ADMIN = ("admin",)
KEY = "key"      # só chave de API com escopo ingest
ANY = "any"      # qualquer credencial válida
PUBLIC = "public"
DEV = "dev"      # só existe com OIDC_MODE=mock (nunca em produção); sem credencial por definição
ENROLL = "enroll"  # sem login por definição: a credencial é o token de matrícula no corpo; coberto por teste próprio (test_enrollment.py)

# Quem pode o quê. É a ÚNICA fonte da verdade do teste: rota nova sem linha aqui reprova (seguro por padrão).
EXPECTED: dict[tuple[str, str], object] = {
    ("GET", "/health"): PUBLIC, ("GET", "/version"): PUBLIC,
    ("GET", "/v1/me"): ANY, ("POST", "/dev/token"): DEV,
    ("GET", "/v1/alerts"): ALL, ("GET", "/v1/taxonomy"): ALL, ("GET", "/v1/stats/overview"): ALL, ("GET", "/v1/stats/categories"): ALL,
    ("GET", "/v1/stats/risk"): ALL, ("GET", "/v1/stats/signals"): ALL, ("GET", "/v1/tenant"): ALL, ("GET", "/v1/events"): ALL, ("GET", "/v1/people"): ALL, ("GET", "/v1/license/status"): ALL, ("PUT", "/v1/device/ias"): KEY, ("GET", "/v1/devices/export.csv"): ("admin", "auditor"), ("POST", "/v1/license/activate"): ("admin",), ("POST", "/v1/license/renew"): ("admin",), ("POST", "/v1/events/{event_id}/feedback"): ("admin", "analista"), ("GET", "/v1/feedback/summary"): ("admin", "analista", "auditor"), ("GET", "/v1/feedback/export.jsonl"): ("admin", "auditor"), ("GET", "/v1/events/export.csv"): ("admin", "auditor"), ("GET", "/v1/events/{event_id}"): ALL,
    ("GET", "/v1/incidents"): ALL, ("GET", "/v1/incidents/{incident_id}"): ALL, ("GET", "/v1/policies"): ALL,
    ("PATCH", "/v1/incidents/{incident_id}"): ("admin", "analista"),
    ("POST", "/v1/events/{event_id}/original"): ("admin", "analista"),          # texto original: só admin e analista, com justificativa
    ("POST", "/v1/policies/simulate"): ("admin", "analista"), ("GET", "/v1/users/directory"): ("admin", "analista"),
    ("GET", "/v1/privacy/data-map"): ("admin", "auditor", "analista"),
    ("GET", "/v1/inference-hook/config"): ("admin", "analista", "auditor"),
    ("GET", "/v1/reports"): ("admin", "analista", "auditor"), ("POST", "/v1/reports"): ("admin", "analista", "auditor"),
    ("GET", "/v1/reports/schedules"): ("admin", "analista", "auditor"), ("GET", "/v1/reports/{report_id}/download"): ("admin", "analista", "auditor"),
    ("GET", "/v1/audit-log"): ("admin", "auditor"), ("GET", "/v1/export/cef"): ("admin", "auditor"),
    ("GET", "/v1/export/events.jsonl"): ("admin", "auditor"), ("GET", "/v1/privacy/subject"): ("admin", "auditor"),
    ("GET", "/v1/api-keys"): ADMIN, ("POST", "/v1/api-keys"): ADMIN, ("POST", "/v1/api-keys/{key_id}/revoke"): ADMIN,
    ("POST", "/v1/api-keys/{key_id}/rotate"): ADMIN, ("GET", "/v1/channels"): ADMIN, ("POST", "/v1/channels"): ADMIN,
    ("PATCH", "/v1/channels/{channel_id}"): ADMIN, ("DELETE", "/v1/channels/{channel_id}"): ADMIN,
    ("POST", "/v1/channels/{channel_id}/test"): ADMIN, ("PATCH", "/v1/tenant"): ADMIN, ("GET", "/v1/users"): ADMIN,
    ("POST", "/v1/users"): ADMIN, ("DELETE", "/v1/users/{user_id}"): ADMIN, ("POST", "/v1/policies"): ADMIN,
    ("PUT", "/v1/policies/{policy_id}"): ADMIN, ("PUT", "/v1/inference-hook/config"): ADMIN, ("PUT", "/v1/inference-hook/secret"): ADMIN,
    ("POST", "/v1/privacy/subject/erase"): ADMIN, ("POST", "/v1/privacy/retention/run"): ADMIN,
    ("POST", "/v1/reports/schedules"): ADMIN, ("DELETE", "/v1/reports/schedules/{schedule_id}"): ADMIN,
    ("DELETE", "/v1/reports/{report_id}"): ADMIN,
    ("POST", "/v1/enroll"): ENROLL,
    ("GET", "/sensor/install.ps1"): PUBLIC, ("GET", "/sensor/install.sh"): PUBLIC,      # sem segredo: o token vai na linha de comando da máquina
    ("GET", "/sensor/promptshield-sensor.pyz"): PUBLIC, ("GET", "/sensor/manifest.json"): PUBLIC,
    ("GET", "/sensor/extension.zip"): PUBLIC, ("GET", "/sensor/extension-manifest.json"): PUBLIC,
    ("GET", "/v1/enrollment-tokens"): ADMIN, ("POST", "/v1/enrollment-tokens"): ADMIN, ("POST", "/v1/enrollment-tokens/{token_id}/revoke"): ADMIN,
    ("GET", "/v1/devices"): ALL, ("POST", "/v1/devices/{device_id}/revoke"): ADMIN,
    ("GET", "/v1/pilot/summary"): ("admin", "analista", "auditor"), ("PUT", "/v1/pilot/config"): ADMIN,
    ("POST", "/v1/pilot/samples"): ("admin", "analista"), ("GET", "/v1/pilot/reviews"): ("admin", "analista"),
    ("PATCH", "/v1/pilot/reviews/{review_id}"): ("admin", "analista"),
    ("POST", "/v1/events"): KEY, ("POST", "/v1/events/{event_id}/justification"): KEY, ("GET", "/v1/hook-config"): KEY,
    ("GET", "/v1/extension-config"): KEY, ("POST", "/v1/inference-hook"): KEY,
}


def _routes() -> list[tuple[str, str]]:
    from app.main import app

    return sorted((m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops)


def _fill(path: str) -> str:
    out = path
    for name in ("event_id", "incident_id", "policy_id", "key_id", "channel_id", "report_id", "schedule_id", "user_id", "review_id"):
        out = out.replace("{" + name + "}", str(uuid.uuid4()))
    return out


def _call(client, method: str, path: str, headers: dict):
    kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
    return client.request(method, _fill(path), headers=headers, **kw)


def test_every_route_has_an_explicit_access_expectation():
    dev = ("POST", "/dev/token")      # só existe se o app foi importado com OIDC_MODE=mock; coberto por teste próprio
    routes = [r for r in _routes() if r != dev]
    assert set(routes) == set(EXPECTED) - {dev}, (f"sem expectativa: {sorted(set(routes) - set(EXPECTED))}; "
                                                 f"expectativa sem rota: {sorted(set(EXPECTED) - set(routes) - {dev})}")


def test_dev_token_route_does_not_exist_unless_mock_mode_is_on():
    import os
    import subprocess
    import sys

    code = "from app.main import app; print(any('/dev/token' in p for p in app.openapi()['paths']))"
    for mode, expected in (("off", "False"), ("oidc", "False"), ("mock", "True")):
        env = {**os.environ, "OIDC_MODE": mode, "OIDC_MOCK_SECRET": "x" * 40}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.strip()
        assert out == expected, mode


def test_no_credentials_means_401_on_every_protected_route(client, world):
    for method, path in _routes():
        if EXPECTED[(method, path)] in (DEV, ENROLL):
            continue
        if EXPECTED[(method, path)] == PUBLIC:
            ok = (200, 503) if path.startswith("/sensor/extension") else (200,)   # 503: a extensão só existe onde foi construída (imagem Docker)
            assert _call(client, method, path, {}).status_code in ok, path
            continue
        r = _call(client, method, path, {})
        assert r.status_code == 401, (method, path, r.status_code)
        r = _call(client, method, path, {"Authorization": "Bearer isto.nao.e.um.token"})
        assert r.status_code == 401, (method, path, r.status_code)
        r = _call(client, method, path, {"X-API-Key": "ps_aaaaaaaa_chave-inventada"})
        assert r.status_code == 401, (method, path, r.status_code)


def test_role_matrix_every_route_every_role(client, world):
    failures = []
    for method, path in _routes():
        rule = EXPECTED[(method, path)]
        if rule in (PUBLIC, DEV, ENROLL):
            continue
        for role in ALL:
            code = _call(client, method, path, world.user(role)).status_code
            allowed = rule == ANY or (isinstance(rule, tuple) and role in rule)
            if allowed and code in (401, 403):
                failures.append(f"{role} deveria poder {method} {path}, recebeu {code}")
            if not allowed and code != 403:
                failures.append(f"{role} NÃO deveria poder {method} {path}, recebeu {code}")
        key_code = _call(client, method, path, world.key()).status_code
        if rule == KEY or rule == ANY:
            assert key_code != 403, (method, path)
        else:
            if key_code != 403:
                failures.append(f"chave de API não deveria acessar {method} {path}, recebeu {key_code}")
    assert failures == []


def test_only_admin_and_analyst_can_ask_for_the_original_text_and_each_ask_is_audited(client, world):
    assert client.patch("/v1/tenant", json={"store_original": True}, headers=world.user("admin")).status_code == 200
    ev = event("segredo AKIAZ7QW4XK2M9PLR3TN")
    assert client.post("/v1/events", json=ev, headers=world.key()).status_code == 200
    body = {"justification": "investigação do incidente 42, autorizada"}
    for role in ("auditor", "leitura"):
        assert client.post(f"/v1/events/{ev['event_id']}/original", json=body, headers=world.user(role)).status_code == 403
    assert client.post(f"/v1/events/{ev['event_id']}/original", json=body, headers=world.key()).status_code == 403
    assert client.post(f"/v1/events/{ev['event_id']}/original", json={"justification": "curta"}, headers=world.user("analista")).status_code == 422
    ok = client.post(f"/v1/events/{ev['event_id']}/original", json=body, headers=world.user("analista"))
    assert ok.status_code == 200 and "AKIAZ7QW4XK2M9PLR3TN" in ok.json()["text"]
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'event.original_read'").scalar() == 1
    for role in ALL:                                                          # nenhuma rota de leitura devolve o original
        for path in (f"/v1/events/{ev['event_id']}", "/v1/events", "/v1/incidents"):
            assert "AKIAZ7QW4XK2M9PLR3TN" not in client.get(path, headers=world.user(role)).text


# ---------- limite de requisições ----------
@pytest.fixture
def limits(monkeypatch):
    ratelimit.reset()
    yield monkeypatch
    ratelimit.reset()


def test_rate_limit_per_api_key_returns_429_with_retry_after(client, world, limits):
    limits.setattr(settings, "rate_limit_key_per_minute", 5)
    codes = [client.post("/v1/events", json=event("oi"), headers=world.key()).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    r = client.post("/v1/events", json=event("oi"), headers=world.key())
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert client.post("/v1/events", json=event("oi"), headers=world.key("b")).status_code == 200       # outra chave: outro balde
    assert world.sql("SELECT count(*) FROM events").scalar() == 6                                          # o bloqueado não foi processado


def test_rate_limit_per_console_user_and_zero_disables(client, world, limits):
    limits.setattr(settings, "rate_limit_user_per_minute", 3)
    assert [client.get("/v1/me", headers=world.user("admin")).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert client.get("/v1/me", headers=world.user("analista")).status_code == 200
    limits.setattr(settings, "rate_limit_user_per_minute", 0)
    assert all(client.get("/v1/me", headers=world.user("admin")).status_code == 200 for _ in range(10))


def test_token_bucket_refills_over_time():
    ratelimit.reset()
    assert [ratelimit.check("k", 60, now=0.0) for _ in range(60)] == [None] * 60
    assert ratelimit.check("k", 60, now=0.0) == 1
    assert ratelimit.check("k", 60, now=1.0) is None                          # 1 ficha por segundo
    assert ratelimit.check("k", 60, now=1.0) == 1
    ratelimit.reset()


# ---------- rotação e expiração de chaves de API ----------
def test_rotation_keeps_old_key_for_the_grace_period_then_expires_it(client, world):
    admin = world.user("admin")
    old = client.post("/v1/api-keys", json={"name": "coletor"}, headers=admin).json()
    new = client.post(f"/v1/api-keys/{old['id']}/rotate", json={"grace_hours": 2}, headers=admin)
    assert new.status_code == 201 and new.json()["key"] != old["key"] and new.json()["replaces"] == old["id"]
    use = lambda k: client.post("/v1/events", json=event("oi"), headers={"X-API-Key": k}).status_code  # noqa: E731
    assert use(old["key"]) == 200 and use(new.json()["key"]) == 200            # convivência
    keys = {k["id"]: k for k in client.get("/v1/api-keys", headers=admin).json()}
    assert keys[old["id"]]["status"] == "expira em breve" and keys[new.json()["id"]]["status"] == "ativa"
    assert "key" not in json.dumps(list(keys.values()))
    world.sql("UPDATE api_keys SET expires_at = now() - interval '1 second' WHERE id = :i", i=old["id"])
    assert use(old["key"]) == 401 and use(new.json()["key"]) == 200            # venceu
    assert {k["id"]: k["status"] for k in client.get("/v1/api-keys", headers=admin).json()}[old["id"]] == "expirada"
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'api_key.rotate'").scalar() == 1


def test_rotation_with_zero_grace_revokes_now_and_never_extends_a_shorter_expiry(client, world):
    admin = world.user("admin")
    a = client.post("/v1/api-keys", json={"name": "a"}, headers=admin).json()
    r = client.post(f"/v1/api-keys/{a['id']}/rotate", json={"grace_hours": 0}, headers=admin).json()
    assert r["old_key_valid_until"] is None
    assert client.post("/v1/events", json=event("oi"), headers={"X-API-Key": a["key"]}).status_code == 401
    assert client.post(f"/v1/api-keys/{a['id']}/rotate", json={}, headers=admin).status_code == 404       # já revogada
    b = client.post("/v1/api-keys", json={"name": "b", "expires_in_days": 1}, headers=admin).json()
    client.post(f"/v1/api-keys/{b['id']}/rotate", json={"grace_hours": 168}, headers=admin)
    exp = world.sql("SELECT expires_at FROM api_keys WHERE id = :i", i=b["id"]).scalar()
    assert exp < datetime.now(timezone.utc) + timedelta(days=1, minutes=1)                                  # continua no máx. 1 dia
    assert client.post("/v1/api-keys", json={"name": "x", "expires_in_days": 0}, headers=admin).status_code == 422
    assert client.post(f"/v1/api-keys/{a['id']}/rotate", json={"grace_hours": 169}, headers=admin).status_code in (404, 422)


def test_rotation_is_tenant_scoped(client, world):
    a = client.post("/v1/api-keys", json={"name": "a"}, headers=world.user("admin")).json()
    assert client.post(f"/v1/api-keys/{a['id']}/rotate", json={}, headers=world.user("admin", tenant="b")).status_code == 404


# ---------- cabeçalhos, métricas e logs ----------
def test_api_responses_carry_safe_headers_and_request_id(client, world):
    r = client.get("/v1/me", headers=world.user("admin"))
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert len(r.headers["x-request-id"]) == 32
    assert client.get("/v1/me", headers={**world.user("admin"), "X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    assert client.get("/v1/me", headers={**world.user("admin"), "X-Request-ID": "x\ny" * 5}).headers["x-request-id"] != "x\ny" * 5
    assert client.get("/v1/me").headers["cache-control"] == "no-store"          # também nas respostas de erro


def test_metrics_are_off_without_token_and_never_carry_tenant_or_user(client, world, monkeypatch):
    metrics.reset()
    client.get("/v1/me", headers=world.user("admin"))
    client.post("/v1/events", json=event("CPF 529.982.247-25", actor={"user_id": "maria@empresa.com"}), headers=world.key())
    assert client.get("/metrics").status_code == 404 and client.get("/metrics", headers={"Authorization": "Bearer x"}).status_code == 404
    monkeypatch.setattr(settings, "metrics_token", "token-de-metricas-de-teste")
    assert client.get("/metrics", headers={"Authorization": "Bearer errado"}).status_code == 404
    text = client.get("/metrics", headers={"Authorization": "Bearer token-de-metricas-de-teste"}).text
    assert 'ps_http_requests_total{method="GET",route="/v1/me",status="200"}' in text
    assert 'ps_events_ingested_total{channel="agent_hook",decision="allow"} 1' in text
    assert "ps_http_request_duration_seconds_bucket" in text
    for forbidden in (world.a["tenant_id"], "maria@empresa.com", "529.982", "admin@a.example.com", world.a["api_key"]):
        assert forbidden not in text


def test_logs_never_contain_prompt_text_emails_or_secrets(client, world, caplog):
    secret, phrase = "AKIAZ7QW4XK2M9PLR3TN", "frase-unica-do-prompt-confidencial"
    caplog.set_level(logging.DEBUG)
    ev = event(f"{phrase} {secret} CPF 529.982.247-25", actor={"user_id": "maria@empresa.com", "department": "RH"})
    client.post("/v1/events", json=ev, headers=world.key())
    client.get("/v1/events", params={"user_id": "maria@empresa.com"}, headers=world.user("admin"))
    client.get(f"/v1/events/{ev['event_id']}", headers=world.user("analista"))
    client.get("/v1/privacy/subject", params={"user_id": "maria@empresa.com"}, headers=world.user("auditor"))
    client.post("/v1/privacy/subject/erase", json={"user_id": "maria@empresa.com", "justification": "pedido do titular, protocolo 1"}, headers=world.user("admin"))
    client.post("/v1/inference-hook", json={"type": "prompt", "messages": [{"role": "user", "content": [{"type": "text", "text": phrase}]}]}, headers=world.key())
    client.post("/v1/events", content=f"isto não é json {phrase}", headers={**world.key(), "Content-Type": "application/json"})
    out = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    for forbidden in (phrase, secret, "529.982", "maria@empresa.com", "admin@a.example.com"):
        assert forbidden not in out, forbidden
    access = [json.loads(JsonFormatter().format(r)) for r in caplog.records if r.name == "promptshield.access"]
    assert access and all(set(a) >= {"route", "method", "status", "duration_ms", "request_id"} for a in access)
    assert any(a["route"] == "/v1/events" and a["tenant_id"] == world.a["tenant_id"] for a in access)       # modelo da rota, não o caminho real
    assert not any("user_id" in a["route"] or "maria" in a["route"] for a in access)


def test_json_formatter_keeps_only_the_exception_type():
    try:
        raise ValueError("mensagem com dado: 529.982.247-25")
    except ValueError:
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "falhou", None, __import__("sys").exc_info())
    line = JsonFormatter().format(rec)
    assert json.loads(line)["exc_type"] == "ValueError" and "529.982" not in line
