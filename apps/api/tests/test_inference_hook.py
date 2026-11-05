"""Etapa 8: endpoint dos inference hooks com requisições simuladas conforme os exemplos da documentação oficial."""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from promptshield_inference_hooks.signature import sign

from app.config import settings

pytestmark = pytest.mark.db

SECRET = "whsec_" + base64.b64encode(bytes([0xFB, 0xEF, 0xBE, 0xFF, 0xFE, 0x3E] * 6)).decode()
SECRET2 = "whsec_" + base64.b64encode(b"segundo-segredo-de-teste-32bytes").decode()
AWS = "AKIAZ7QW4XK2M9PLR3TN"
URL = "/v1/inference-hook"

DOC_EXAMPLE = {  # corpo do exemplo da documentação
    "type": "prompt", "request_id": "req_abc123", "tenant_id": "11111111-1111-1111-1111-111111111111",
    "actor": {"type": "user", "id": "user_01AbCdEfGhIjKlMnOpQrStUv", "email_address": "alice@example.com"},
    "source": {"application": "claude-ai"}, "session_id": "22222222-2222-2222-2222-222222222222", "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Summarize the attached report."},
        {"type": "attachment", "file_name": "q2-report.pdf", "media_type": "application/pdf", "size_bytes": 48213,
         "text": "Q2 revenue grew 14% quarter over quarter..."}]}],
    "metadata": {},
}


def frame(text=None, *, rid=None, session="sess-1", app="claude-ai", extra_messages=(), blocks=None):
    content = blocks if blocks is not None else [{"type": "text", "text": text}]
    return {**DOC_EXAMPLE, "request_id": rid or f"req_{uuid.uuid4().hex[:10]}", "session_id": session, "source": {"application": app},
            "messages": [*extra_messages, {"role": "user", "content": content}]}


def call(client, world, body, *, secret=SECRET, ts=None, key=True, signed=True, rid=None, who="a"):
    raw = json.dumps(body).encode()
    rid = rid or body.get("request_id") or "req_x"
    ts = int(time.time()) if ts is None else ts
    headers = {"Content-Type": "application/json"}
    if key:
        headers.update(world.key(who))
    if signed:
        headers.update({"webhook-id": rid, "webhook-timestamp": str(ts), "webhook-signature": sign(secret, rid, ts, raw)})
    return client.post(URL, content=raw, headers=headers)


@pytest.fixture
def hook(client, world):
    """Segredo configurado, modo sombra (o padrão)."""
    r = client.put(f"{URL}/secret", json={"secret": SECRET}, headers=world.user("admin"))
    assert r.status_code == 200 and r.json()["has_secret"] and r.json()["mode"] == "shadow"
    return world


def enforce(client, world, *, mode="enforce", **extra):
    r = client.put(f"{URL}/config", json={"mode": mode, **extra}, headers=world.user("admin"))
    assert r.status_code == 200, r.text
    return r.json()


def set_policy_mode(client, world, name, mode):
    pols = {p["name"]: p for p in client.get("/v1/policies", headers=world.user("admin")).json()}
    p = pols[name]
    body = {k: p[k] for k in ("name", "description", "enabled", "scope", "match", "action")} | {"mode": mode}
    assert client.put(f"/v1/policies/{p['id']}", json=body, headers=world.user("admin")).status_code == 200


SEG, ENV = "Bloquear segredos e chaves", "Bloquear leitura de .env e credenciais"


# ---------- exemplo da documentação, autenticação, assinatura ----------
def test_doc_example_is_allowed_and_recorded_in_shadow_with_partial_status(client, hook):
    r = call(client, hook, DOC_EXAMPLE)
    assert r.status_code == 200 and r.json() == {"action": "allow"}
    rows = hook.sql("SELECT channel, app, integration_status, kind, user_id FROM events ORDER BY kind").all()
    assert [(x.channel, x.app, x.integration_status, x.kind, x.user_id) for x in rows] == [
        ("inference_hook", "claude_ai", "partial", "file_upload", "alice@example.com"),
        ("inference_hook", "claude_ai", "partial", "prompt", "alice@example.com")]
    req = hook.sql("SELECT frame_type, application, outcome, blocks_total, blocks_new, latency_ms FROM inference_hook_requests").one()
    assert (req.frame_type, req.application, req.outcome, req.blocks_total, req.blocks_new) == ("prompt", "claude_ai", "allow", 2, 2)


def test_unsigned_wrong_signature_stale_timestamp_and_wrong_key_are_rejected(client, hook):
    body = frame("oi")
    assert call(client, hook, body, signed=False).status_code == 401
    assert call(client, hook, body, secret=SECRET2).status_code == 401
    assert call(client, hook, body, ts=int(time.time()) - 400).status_code == 401
    assert call(client, hook, body, key=False).status_code == 401                      # sem chave de API: não identifica o tenant
    assert call(client, hook, body, who="b").status_code == 401                        # chave do tenant B + segredo do A: nada passa
    assert hook.sql("SELECT count(*) FROM events").scalar() == 0
    cfg = hook.sql("SELECT rejected_count, last_rejected_at FROM inference_hook_configs "
                   "WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'empresa-a')").one()
    assert cfg.rejected_count == 3 and cfg.last_rejected_at is not None                # sem chave de API nem chega a contar; a do B conta no B


def test_no_secret_configured_rejects_everything(client, world):
    assert call(client, world, frame("oi")).status_code == 401


def test_invalid_json_and_oversize_body(client, hook, monkeypatch):
    raw = b"isto nao e json"
    ts = int(time.time())
    h = {**hook.key(), "webhook-id": "r1", "webhook-timestamp": str(ts), "webhook-signature": sign(SECRET, "r1", ts, raw)}
    assert client.post(URL, content=raw, headers=h).status_code == 400
    monkeypatch.setattr(settings, "inference_hook_max_body_bytes", 100)
    assert call(client, hook, frame("x" * 500)).status_code == 413


def test_unknown_type_and_config_test_are_allowed_without_events(client, hook):
    r = call(client, hook, {**frame("oi"), "type": "response"})
    assert r.status_code == 200 and r.json() == {"action": "allow"}
    r = call(client, hook, frame("synthetic test prompt", app="config-test"))
    assert r.status_code == 200 and r.json() == {"action": "allow"}
    assert hook.sql("SELECT count(*) FROM events").scalar() == 0
    cfg = client.get(f"{URL}/config", headers=hook.user("admin")).json()
    assert cfg["last_test_at"] is not None and cfg["stats_24h"]["requests"] == 1  # o teste de conexão não conta nas estatísticas


# ---------- sombra x aplicar ----------
def test_prompt_with_synthetic_secret_is_denied_in_enforce_and_allowed_in_shadow(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    shadow = call(client, hook, frame(f"use {AWS} no deploy"))
    assert shadow.json() == {"action": "allow"}                                        # modo do hook = sombra (padrão)
    ev = hook.sql("SELECT a.decision, a.would_decide FROM analyses a JOIN events e ON e.id = a.event_pk").one()
    assert (ev.decision, ev.would_decide) == ("allow", "block")                          # grava o que teria decidido
    assert hook.sql("SELECT outcome, would_deny FROM inference_hook_requests").one() == ("shadow_allow", True)

    enforce(client, hook)
    r = call(client, hook, frame(f"use {AWS} no deploy", session="outra"))
    v = r.json()
    assert r.status_code == 200 and v["action"] == "deny"
    assert "segredo" in v["deny_reason"].lower() and AWS not in json.dumps(v) and len(v["deny_reason"]) <= 500
    assert v["reference_id"].startswith("ps:") and len(v["reference_id"]) <= 50
    assert hook.sql("SELECT reference_id FROM inference_hook_requests WHERE outcome = 'deny'").scalar() == v["reference_id"]
    assert AWS not in hook.sql("SELECT string_agg(masked_text, ' ') FROM events").scalar()


def test_policy_in_monitor_mode_never_denies_even_when_hook_enforces(client, hook):
    enforce(client, hook)
    assert call(client, hook, frame(f"use {AWS} no deploy")).json() == {"action": "allow"}  # política nasce em monitorar
    assert hook.sql("SELECT would_deny FROM inference_hook_requests").scalar() is True


def test_mask_decision_becomes_deny_because_the_hook_cannot_rewrite(client, hook):
    set_policy_mode(client, hook, "Mascarar CPF, CNPJ e contato", "enforce")
    enforce(client, hook)
    v = call(client, hook, frame("meu cpf é 529.982.247-25, resuma o contrato")).json()
    assert v["action"] == "deny" and "529.982" not in json.dumps(v)


def test_cannot_enforce_without_secret_and_config_is_admin_only(client, world):
    assert client.put(f"{URL}/config", json={"mode": "enforce"}, headers=world.user("admin")).status_code == 409
    assert client.put(f"{URL}/config", json={"mode": "shadow"}, headers=world.user("analista")).status_code == 403
    assert client.put(f"{URL}/secret", json={"secret": SECRET}, headers=world.user("analista")).status_code == 403
    assert client.get(f"{URL}/config", headers=world.user("leitura")).status_code == 403
    assert client.get(f"{URL}/config", headers=world.user("auditor")).status_code == 200
    assert client.put(f"{URL}/secret", json={"secret": "whsec_@@@"}, headers=world.user("admin")).status_code == 422
    assert client.put(f"{URL}/secret", json={"secret": "whsec_" + base64.b64encode(b"curto").decode()}, headers=world.user("admin")).status_code == 422


def test_secret_never_leaves_the_api_and_is_encrypted_at_rest(client, hook):
    cfg = client.get(f"{URL}/config", headers=hook.user("admin")).json()
    assert SECRET not in json.dumps(cfg) and SECRET.removeprefix("whsec_") not in json.dumps(cfg) and "ciphertext" not in json.dumps(cfg)
    raw = bytes(hook.sql("SELECT secret_ciphertext FROM inference_hook_configs").scalar())
    assert SECRET.encode() not in raw and SECRET.removeprefix("whsec_").encode() not in raw
    assert hook.sql("SELECT count(*) FROM audit_log WHERE action = 'inference_hook.secret'").scalar() == 1
    assert SECRET not in json.dumps(hook.sql("SELECT detail FROM audit_log WHERE action = 'inference_hook.secret'").scalar())


# ---------- tool_call ----------
TOOL_USE = {"type": "tool_use", "id": "toolu_1", "tool_name": "bash", "input": {"command": "cat ~/.aws/credentials"},
            "tool_info": {"type": "client", "tool_type": "bash_20250124"}}


def tool_frame(rid=None, use=TOOL_USE, app="claude-code"):
    return {**DOC_EXAMPLE, "type": "tool_call", "request_id": rid or f"req_{uuid.uuid4().hex[:10]}", "source": {"application": app},
            "messages": [{"role": "user", "content": [{"type": "text", "text": "mensagem antiga, ignorada neste frame"}]},
                         {"role": "assistant", "content": [{"type": "text", "text": "vou ler"}, use]}]}


def test_tool_call_frame_denies_credential_read_and_respects_validate_toggle(client, hook):
    set_policy_mode(client, hook, ENV, "enforce")
    enforce(client, hook)
    v = call(client, hook, tool_frame()).json()
    assert v["action"] == "deny" and "ação pedida" in v["deny_reason"]
    ev = hook.sql("SELECT kind, tool_name, channel, app FROM events WHERE kind = 'tool_call'").one()
    assert (ev.kind, ev.tool_name, ev.channel, ev.app) == ("tool_call", "bash", "inference_hook", "claude_code")
    assert hook.sql("SELECT count(*) FROM events WHERE kind = 'prompt'").scalar() == 0     # só o último turno do assistente
    enforce(client, hook, evaluate_tool_calls=False)
    other = {**TOOL_USE, "id": "toolu_2", "input": {"command": "cat ~/.aws/credentials # de novo"}}
    assert call(client, hook, tool_frame(use=other)).json() == {"action": "allow"}


def test_tool_call_in_a_later_prompt_frame_is_only_recorded_never_denies(client, hook):
    set_policy_mode(client, hook, ENV, "enforce")
    enforce(client, hook, evaluate_tool_calls=False)                                       # "Validate tool calls" desligado
    history = [{"role": "assistant", "content": [{k: v for k, v in TOOL_USE.items() if k != "tool_info"}]}]
    body = frame("e agora?", extra_messages=history, app="claude-code")
    assert call(client, hook, body).json() == {"action": "allow"}                         # o comando já rodou: negar o próximo prompt não o desfaz
    ev = hook.sql("SELECT a.decision, a.would_decide FROM analyses a JOIN events e ON e.id = a.event_pk WHERE e.kind = 'tool_call'").one()
    assert (ev.decision, ev.would_decide) == ("allow", "block")                             # visível no console, sem derrubar o usuário


# ---------- transcrição inteira reenviada a cada turno ----------
def test_denial_persists_while_the_denied_message_stays_and_clears_after_edit(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    enforce(client, hook)
    bad = {"role": "user", "content": [{"type": "text", "text": f"minha chave é {AWS}"}]}
    assert call(client, hook, frame("primeira", extra_messages=[])).json()["action"] == "allow"
    assert call(client, hook, frame(f"minha chave é {AWS}")).json()["action"] == "deny"
    again = call(client, hook, frame("continue, por favor", extra_messages=[bad]))           # a mensagem negada continua na transcrição
    assert again.json()["action"] == "deny"
    clean = {"role": "user", "content": [{"type": "text", "text": "minha chave foi removida"}]}
    assert call(client, hook, frame("continue, por favor", extra_messages=[clean])).json()["action"] == "allow"   # editada: libera


def test_latest_scope_only_looks_at_the_last_user_message(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    enforce(client, hook, scope="latest")
    bad = {"role": "user", "content": [{"type": "text", "text": f"minha chave é {AWS}"}]}
    assert call(client, hook, frame("continue", extra_messages=[bad])).json()["action"] == "allow"
    assert hook.sql("SELECT count(*) FROM events").scalar() == 1                             # só a última mensagem foi analisada


def test_repeated_transcript_blocks_are_analyzed_once(client, hook):
    old = [{"role": "user", "content": [{"type": "text", "text": f"mensagem {i}"}]} for i in range(5)]
    assert call(client, hook, frame("agora", extra_messages=old)).status_code == 200
    n_first = hook.sql("SELECT count(*) FROM events").scalar()
    r = call(client, hook, frame("agora de novo", extra_messages=[*old, {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}]))
    assert r.status_code == 200
    new = hook.sql("SELECT blocks_total, blocks_new FROM inference_hook_requests ORDER BY created_at DESC LIMIT 1").one()
    assert n_first == 6 and new.blocks_total == 7 and new.blocks_new == 2                    # só a resposta nova e o prompt novo
    assert hook.sql("SELECT count(*) FROM events WHERE kind = 'response'").scalar() == 1


def test_retry_with_same_webhook_id_returns_same_verdict_and_does_not_duplicate(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    enforce(client, hook)
    body = frame(f"use {AWS}", rid="req_retry")
    a = call(client, hook, body, rid="req_retry").json()
    n = hook.sql("SELECT count(*) FROM events").scalar()
    b = call(client, hook, body, rid="req_retry").json()
    assert a["action"] == b["action"] == "deny"
    assert hook.sql("SELECT count(*) FROM events").scalar() == n == 1
    assert hook.sql("SELECT count(*) FROM inference_hook_requests WHERE request_id = 'req_retry'").scalar() == 1


def test_attachment_text_and_tool_result_are_inspected_but_image_only_is_counted(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    enforce(client, hook)
    blocks = [{"type": "attachment", "file_name": "env.txt", "media_type": "text/plain", "size_bytes": 20, "text": f"AWS_KEY={AWS}"},
              {"type": "attachment", "file_name": None, "media_type": "image/png", "size_bytes": 99, "text": None}]
    assert call(client, hook, frame(blocks=blocks)).json()["action"] == "deny"
    assert hook.sql("SELECT skipped_attachments FROM inference_hook_requests").scalar() == 1
    result = [{"type": "tool_result", "tool_use_id": "t1", "tool_name": "read_file", "content": f"token {AWS}", "is_error": False}]
    assert call(client, hook, frame(blocks=result, session="s-tool")).json()["action"] == "deny"
    assert hook.sql("SELECT count(*) FROM events WHERE kind = 'tool_result'").scalar() == 1


# ---------- falha própria e rotação ----------
def test_failure_mode_follows_tenant_setting_and_shadow_always_allows(client, hook, monkeypatch):
    monkeypatch.setattr(settings, "inference_hook_budget_ms", -1)                           # estoura o orçamento no primeiro bloco
    assert call(client, hook, frame("oi")).json() == {"action": "allow"}                     # sombra: sempre permite
    assert hook.sql("SELECT outcome, error FROM inference_hook_requests").one() == ("failure_allow", "orçamento de tempo estourado")
    enforce(client, hook)
    hook.sql("UPDATE tenants SET failure_mode = 'open' WHERE slug = 'empresa-a'")
    assert call(client, hook, frame("oi dois")).json() == {"action": "allow"}
    hook.sql("UPDATE tenants SET failure_mode = 'closed' WHERE slug = 'empresa-a'")
    v = call(client, hook, frame("oi três")).json()
    assert v["action"] == "deny" and "não conseguiu verificar" in v["deny_reason"] and v["reference_id"].startswith("ps:")
    assert client.get(f"{URL}/config", headers=hook.user("admin")).json()["stats_24h"]["failures"] == 3


def test_internal_error_follows_failure_mode_and_logs_no_content(client, hook, monkeypatch, caplog):
    import app.inference_hook as ih

    def boom(*a, **k):
        raise RuntimeError(f"explodiu com {AWS}")

    monkeypatch.setattr(ih, "ingest", boom)
    enforce(client, hook)
    hook.sql("UPDATE tenants SET failure_mode = 'closed' WHERE slug = 'empresa-a'")
    with caplog.at_level("DEBUG"):
        v = call(client, hook, frame("qualquer coisa")).json()
    assert v["action"] == "deny"
    assert AWS not in caplog.text and "RuntimeError" in caplog.text
    assert hook.sql("SELECT error FROM inference_hook_requests").scalar() == "erro interno (RuntimeError)"


def test_secret_rotation_accepts_previous_secret_for_a_while(client, hook):
    assert client.put(f"{URL}/secret", json={"secret": SECRET2}, headers=hook.user("admin")).json()["previous_secret_active"] is True
    assert call(client, hook, frame("novo"), secret=SECRET2).status_code == 200
    assert call(client, hook, frame("retardatário"), secret=SECRET).status_code == 200      # assinado com o antigo, ainda aceito
    hook.sql("UPDATE inference_hook_configs SET previous_expires_at = now() - interval '1 minute'")
    assert call(client, hook, frame("depois da janela"), secret=SECRET).status_code == 401
    assert call(client, hook, frame("segue"), secret=SECRET2).status_code == 200


# ---------- tenants e desempenho ----------
def test_tenants_are_isolated(client, hook):
    other = hook.b["api_key"]
    admin_b = hook.user("admin", tenant="b")
    assert client.put(f"{URL}/secret", json={"secret": SECRET2}, headers=admin_b).status_code == 200
    raw = json.dumps(frame(f"segredo do B {AWS}")).encode()
    ts = int(time.time())
    h = {"X-API-Key": other, "webhook-id": "rb", "webhook-timestamp": str(ts), "webhook-signature": sign(SECRET2, "rb", ts, raw)}
    assert client.post(URL, content=raw, headers=h).status_code == 200
    assert hook.sql("SELECT count(*) FROM events WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'empresa-a')").scalar() == 0
    assert client.get(f"{URL}/config", headers=hook.user("admin")).json()["stats_24h"]["requests"] == 0
    assert client.get(f"{URL}/config", headers=admin_b).json()["stats_24h"]["requests"] == 1


def test_latency_is_recorded_and_realistic_transcript_stays_within_budget(client, hook):
    old = [{"role": "user" if i % 2 == 0 else "assistant", "content": [{"type": "text", "text": f"mensagem anterior {i} " * 20}]} for i in range(30)]
    t0 = time.monotonic()
    assert call(client, hook, frame("pergunta nova", extra_messages=old)).status_code == 200
    assert (time.monotonic() - t0) * 1000 < settings.inference_hook_budget_ms        # 31 blocos novos, banco local
    s = client.get(f"{URL}/config", headers=hook.user("admin")).json()["stats_24h"]
    assert s["requests"] == 1 and 0 <= s["p95_ms"] < settings.inference_hook_budget_ms


def test_alerts_still_work_for_events_arriving_through_the_hook(client, hook):
    set_policy_mode(client, hook, SEG, "enforce")
    call(client, hook, frame(f"chave {AWS}"))                                                 # sombra: registra e alerta, não bloqueia
    alerts = client.get("/v1/alerts", headers=hook.user("admin")).json()
    assert any(a["rule"] == "severidade" and a["user_id"] == "alice@example.com" for a in alerts)
    assert datetime.now(timezone.utc) - timedelta(minutes=1) < datetime.now(timezone.utc)
