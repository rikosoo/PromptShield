"""Etapa 9, privacidade: chave por tenant, retenção, direitos do titular, auditoria pseudônima."""
from __future__ import annotations

import base64
import json
import uuid

import pytest
from conftest import event
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app import crypto, worker
from app.config import settings

pytestmark = pytest.mark.db
SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def post(client, world, body, who="a"):
    r = client.post("/v1/events", json=body, headers=world.key(who))
    assert r.status_code == 200, r.text
    return r.json()


def with_original(client, world):
    assert client.patch("/v1/tenant", json={"store_original": True}, headers=world.user("admin")).json()["store_original"] is True


def tid(world, who="a"):
    return uuid.UUID(getattr(world, who)["tenant_id"])


# ---------- chave por tenant ----------
def test_each_tenant_has_its_own_data_key_wrapped_by_the_master_key(client, world):
    a, b = tid(world), tid(world, "b")
    blob = crypto.encrypt_original(a, "texto sintético de teste")
    assert blob.startswith(b"v2.") and b"texto" not in blob
    assert crypto.decrypt_original(a, blob) == "texto sintético de teste"
    with pytest.raises(InvalidToken):
        crypto.decrypt_original(b, blob)                              # a chave do B não abre o texto do A
    crypto.encrypt_original(b, "x")
    keys = world.sql("SELECT tenant_id, data_key_wrapped FROM tenant_keys").all()
    assert len(keys) == 2 and keys[0].data_key_wrapped != keys[1].data_key_wrapped
    master_raw = base64.urlsafe_b64decode(settings.original_text_master_key)
    assert all(master_raw not in bytes(k.data_key_wrapped) for k in keys)   # a DEK não é a chave mestra
    world.sql("DELETE FROM tenants WHERE id = :t", t=a)
    assert world.sql("SELECT count(*) FROM tenant_keys WHERE tenant_id = :t", t=a).scalar() == 0   # apagar o tenant apaga a chave


def test_legacy_ciphertext_without_prefix_still_decrypts(client, world):
    import base64 as b64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    t = tid(world)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"promptshield/original/" + t.bytes).derive(
        b64.urlsafe_b64decode(settings.original_text_master_key))
    legacy = Fernet(b64.urlsafe_b64encode(key)).encrypt("texto antigo".encode())
    assert crypto.decrypt_original(t, legacy) == "texto antigo"


def test_master_key_rotation_rewraps_without_reencrypting(client, world, admin_engine):
    with_original(client, world)
    r = post(client, world, event(f"chave {SECRET}"))
    old_master = settings.original_text_master_key
    new_master = base64.urlsafe_b64encode(b"n" * 32).decode()
    before = bytes(world.sql("SELECT original_ciphertext FROM events").scalar())
    with Session(admin_engine) as s, s.begin():
        assert crypto.rewrap_keys(s, old_master, new_master) == 1
    settings.original_text_master_key = new_master
    try:
        crypto.clear_cache()
        assert bytes(world.sql("SELECT original_ciphertext FROM events").scalar()) == before        # dados não foram recifrados
        out = client.post(f"/v1/events/{r['event_id']}/original", json={"justification": "teste de rotação de chave mestra"},
                          headers=world.user("admin"))
        assert out.status_code == 200 and SECRET in out.json()["text"]
        settings.original_text_master_key = old_master
        crypto.clear_cache()
        with pytest.raises(InvalidToken):
            crypto.decrypt_original(tid(world), before)                                                # a chave antiga não serve mais
    finally:
        settings.original_text_master_key = old_master
        crypto.clear_cache()


def test_channel_url_is_encrypted_at_rest(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_webhooks", True)
    monkeypatch.setattr(settings, "allow_private_webhook_targets", True)
    url = "http://127.0.0.1:9/hooks/T000/B000/segredo-do-slack"
    r = client.post("/v1/channels", json={"kind": "slack", "name": "s", "target": url}, headers=world.user("admin"))
    assert r.status_code == 201 and "segredo-do-slack" not in r.text
    row = world.sql("SELECT target, target_ciphertext FROM notification_channels").one()
    assert "segredo-do-slack" not in row.target and url.encode() not in bytes(row.target_ciphertext)
    assert crypto.decrypt_secret(tid(world), row.target_ciphertext) == url


# ---------- retenção ----------
def age(world, event_id, days):
    world.sql("UPDATE events SET received_at = now() - make_interval(days => :d) WHERE event_id = :e", d=days, e=event_id)


def test_retention_deletes_what_expired_and_only_that(client, world):
    with_original(client, world)
    ids = {}
    for name, days in (("velho", 100), ("meio", 40), ("novo", 5)):
        ev = event(f"chave {SECRET} {name}")
        post(client, world, ev)
        age(world, ev["event_id"], days)
        ids[name] = ev["event_id"]
    other = event(f"chave {SECRET} do outro tenant")
    post(client, world, other, who="b")
    age(world, other["event_id"], 400)                                  # fora do prazo, mas é de outro tenant

    world.sql("UPDATE alerts SET last_seen = now() - interval '100 days' WHERE title LIKE '%'")
    world.sql("INSERT INTO inference_hook_requests (tenant_id, request_id, frame_type, application, outcome) "
              "VALUES (:t, 'velha', 'prompt', 'x', 'allow')", t=tid(world))
    world.sql("UPDATE inference_hook_requests SET created_at = now() - interval '100 days'")
    world.sql("INSERT INTO reports (tenant_id, kind, format, period_start, period_end, content, sha256, created_by, created_at) "
              "VALUES (:t, 'lgpd', 'csv', '2026-01-01', '2026-01-31', 'x', 'h', 'teste', now() - interval '100 days')", t=tid(world))

    counts = client.post("/v1/privacy/retention/run", headers=world.user("admin")).json()
    assert counts["events"] == 1 and counts["originals_erased"] == 2    # o velho (100 d) e o do meio (40 d, passou dos 30 d do original)
    assert counts["hook_requests"] == 1 and counts["reports"] == 1 and counts["alerts"] >= 1
    left = {r.event_id: r.original_ciphertext is not None for r in world.sql(
        "SELECT event_id::text AS event_id, original_ciphertext FROM events WHERE tenant_id = :t", t=tid(world))}
    assert ids["velho"] not in left
    assert left[ids["meio"]] is False and left[ids["novo"]] is True     # o meio perdeu só o original; o novo está inteiro
    assert world.sql("SELECT count(*) FROM analyses a JOIN events e ON e.id = a.event_pk WHERE e.tenant_id = :t", t=tid(world)).scalar() == 2
    assert world.sql("SELECT count(*) FROM incidents i JOIN events e ON e.id = i.event_pk WHERE e.tenant_id = :t", t=tid(world)).scalar() == 2
    assert world.sql("SELECT count(*) FROM events WHERE tenant_id = :t", t=tid(world, "b")).scalar() == 1   # o outro tenant não foi tocado
    log = world.sql("SELECT actor_type, detail FROM audit_log WHERE action = 'retention.run'").one()
    assert log.detail["events"] == 1 and log.detail["retention_days"] == 90


def test_original_retention_never_exceeds_general_retention_and_is_validated(client, world):
    assert client.patch("/v1/tenant", json={"original_retention_days": 0}, headers=world.user("admin")).status_code == 422
    assert client.patch("/v1/tenant", json={"retention_days": 7, "original_retention_days": 30}, headers=world.user("admin")).status_code == 200
    with_original(client, world)
    ev = event("x")
    post(client, world, ev)
    age(world, ev["event_id"], 8)
    assert client.post("/v1/privacy/retention/run", headers=world.user("admin")).json()["events"] == 1   # vale o menor prazo (7 dias)
    assert client.post("/v1/privacy/retention/run", headers=world.user("analista")).status_code == 403


def test_worker_runs_retention_once_a_day(client, world):
    ev = event(f"chave {SECRET}")
    post(client, world, ev)
    age(world, ev["event_id"], 200)
    assert worker.run_retention(tid(world)) is True
    assert world.sql("SELECT count(*) FROM events").scalar() == 0
    assert worker.run_retention(tid(world)) is False                    # já rodou hoje
    world.sql("UPDATE tenants SET last_retention_run = now() - interval '25 hours' WHERE id = :t", t=tid(world))
    assert worker.run_retention(tid(world)) is True


# ---------- direitos do titular ----------
def test_subject_access_and_erasure_leave_other_people_and_tenants_alone(client, world):
    with_original(client, world)
    mine = [event(f"CPF 529.982.247-25 {i}", actor={"user_id": "maria@empresa.com", "department": "RH"}) for i in range(3)]
    for e in mine:
        post(client, world, e)
    post(client, world, event("oi", actor={"user_id": "joao@empresa.com", "department": "RH"}))
    post(client, world, event("oi", actor={"user_id": "maria@empresa.com"}), who="b")                # mesma pessoa em outro tenant

    exp = client.get("/v1/privacy/subject", params={"user_id": "maria@empresa.com"}, headers=world.user("auditor")).json()
    assert len(exp["events"]) == 3 and exp["incidents"] >= 0
    assert "529.982" not in json.dumps(exp) and all(e["has_original"] for e in exp["events"])         # só mascarado; original nunca sai
    assert client.get("/v1/privacy/subject", params={"user_id": "maria@empresa.com"}, headers=world.user("analista")).status_code == 403

    body = {"user_id": "maria@empresa.com", "justification": "pedido do titular, protocolo 123"}
    assert client.post("/v1/privacy/subject/erase", json=body, headers=world.user("auditor")).status_code == 403
    assert client.post("/v1/privacy/subject/erase", json={**body, "justification": "curto"}, headers=world.user("admin")).status_code == 422
    r = client.post("/v1/privacy/subject/erase", json=body, headers=world.user("admin")).json()
    assert r["events_deleted"] == 3 and "reports_to_review" in r
    assert world.sql("SELECT count(*) FROM events WHERE user_id = 'maria@empresa.com' AND tenant_id = :t", t=tid(world)).scalar() == 0
    assert world.sql("SELECT count(*) FROM events WHERE user_id = 'joao@empresa.com'").scalar() == 1
    assert world.sql("SELECT count(*) FROM events WHERE user_id = 'maria@empresa.com' AND tenant_id = :t", t=tid(world, "b")).scalar() == 1
    assert world.sql("SELECT count(*) FROM analyses a JOIN events e ON e.id = a.event_pk WHERE e.tenant_id = :t", t=tid(world)).scalar() == 1
    logs = world.sql("SELECT action, target_id, detail FROM audit_log WHERE action LIKE 'privacy.%' ORDER BY id").all()
    assert [x.action for x in logs] == ["privacy.subject_export", "privacy.subject_erase"]
    assert all("maria@empresa.com" not in json.dumps(x.detail) and "maria@empresa.com" not in x.target_id for x in logs)  # só o hash
    assert logs[1].detail["events"] == 3


def test_erasure_removes_queued_notifications_about_the_person(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_webhooks", True)
    monkeypatch.setattr(settings, "allow_private_webhook_targets", True)
    client.post("/v1/channels", json={"kind": "webhook", "name": "w", "target": "http://127.0.0.1:9/x", "min_severity": "baixo"}, headers=world.user("admin"))
    post(client, world, event(f"chave {SECRET}", actor={"user_id": "maria@empresa.com"}))
    assert world.sql("SELECT count(*) FROM notification_outbox").scalar() >= 1
    client.post("/v1/privacy/subject/erase", json={"user_id": "maria@empresa.com", "justification": "pedido do titular, protocolo 9"},
                headers=world.user("admin"))
    assert world.sql("SELECT count(*) FROM notification_outbox").scalar() == 0
    assert world.sql("SELECT count(*) FROM alerts").scalar() == 0


def test_data_map_reports_what_is_stored(client, world):
    with_original(client, world)
    post(client, world, event("oi", actor={"user_id": "a@x.com"}))
    post(client, world, event("oi", actor={"user_id": "b@x.com"}))
    m = client.get("/v1/privacy/data-map", headers=world.user("auditor")).json()
    assert m["counts"]["events"] == 2 and m["counts"]["distinct_monitored_people"] == 2 and m["counts"]["events_with_original"] == 2
    assert m["original_text_stored"] is True and m["retention_days"] == 90 and m["original_retention_days"] == 30
    assert client.get("/v1/privacy/data-map", headers=world.user("leitura")).status_code == 403


# ---------- usuários do console e auditoria pseudônima ----------
def test_audit_log_keeps_only_the_user_uuid_and_survives_user_removal(client, world):
    admin = world.user("admin")
    new = client.post("/v1/users", json={"email": "temp@a.example.com", "role": "admin"}, headers=admin).json()
    temp = world.tok("temp@a.example.com")
    client.post("/v1/policies", json={"name": "p", "action": "alert", "match": {"categories": ["pii"]}}, headers=temp)
    raw = world.sql("SELECT actor_type, actor_id FROM audit_log WHERE action = 'policy.create'").one()
    assert raw.actor_id == new["id"] and "@" not in raw.actor_id                      # o registro imutável guarda só o UUID
    log = client.get("/v1/audit-log", headers=admin).json()
    assert next(x for x in log if x["action"] == "policy.create")["actor"] == "temp@a.example.com"
    assert client.delete(f"/v1/users/{new['id']}", headers=admin).status_code == 204
    log = client.get("/v1/audit-log", headers=admin).json()
    assert next(x for x in log if x["action"] == "policy.create")["actor"] == "(usuário removido)"
    assert "temp@a.example.com" not in json.dumps(log)
    assert client.get("/v1/me", headers=temp).status_code == 401                         # e ele não entra mais


def test_cannot_remove_yourself_or_the_last_admin_and_only_admins_remove(client, world):
    me = client.get("/v1/me", headers=world.user("admin")).json()["id"]
    assert client.delete(f"/v1/users/{me}", headers=world.user("admin")).status_code == 409
    analista = client.get("/v1/me", headers=world.user("analista")).json()["id"]
    assert client.delete(f"/v1/users/{analista}", headers=world.user("analista")).status_code == 403
    second = client.post("/v1/users", json={"email": "dois@a.example.com", "role": "admin"}, headers=world.user("admin")).json()
    assert client.delete(f"/v1/users/{me}", headers=world.tok("dois@a.example.com")).status_code == 204   # agora há outro admin
    assert client.delete(f"/v1/users/{second['id']}", headers=world.tok("dois@a.example.com")).status_code == 409   # ele é o último


# ---------- texto livre sensível (o mascaramento só cobre identificadores estruturados) ----------
HEALTH = "Prontuário do paciente: diagnóstico CID J45, tomar 10 mg ao dia."


def test_health_text_is_not_stored_by_default_but_is_still_classified(client, world):
    r = post(client, world, event(HEALTH))
    assert "saude" in {c["id"] for c in r["categories"]}
    assert r["masked_text"].startswith("[texto não guardado: categoria ")
    row = world.sql("SELECT masked_text, text_length FROM events").one()
    assert "CID" not in row.masked_text and "paciente" not in row.masked_text and row.text_length == len(HEALTH)
    listed = client.get("/v1/events", headers=world.user("admin")).json()[0]
    assert "J45" not in json.dumps(listed) and "paciente" not in json.dumps(listed) and listed["risk_score"] > 0


def test_health_original_is_kept_encrypted_only_if_the_tenant_enabled_it(client, world):
    with_original(client, world)
    r = post(client, world, event(HEALTH))
    assert "CID" not in r["masked_text"]
    out = client.post(f"/v1/events/{r['event_id']}/original", json={"justification": "revisão autorizada pelo encarregado"}, headers=world.user("admin"))
    assert out.status_code == 200 and "CID J45" in out.json()["text"]       # o original cifrado continua disponível com justificativa


def test_omit_categories_are_configurable_validated_and_do_not_touch_structured_masking(client, world):
    admin = world.user("admin")
    assert client.get("/v1/tenant", headers=admin).json()["omit_text_categories"] == ["saude"]
    assert client.patch("/v1/tenant", json={"omit_text_categories": ["nao_existe"]}, headers=admin).status_code == 422
    masked = post(client, world, event("Cliente CPF 529.982.247-25"))["masked_text"]
    assert masked == "Cliente CPF ***.***.***-25"                              # CPF segue mascarado normalmente
    assert client.patch("/v1/tenant", json={"omit_text_categories": []}, headers=admin).json()["omit_text_categories"] == []
    assert post(client, world, event(HEALTH))["masked_text"] == HEALTH           # o cliente pode optar por guardar o texto
    assert client.patch("/v1/tenant", json={"omit_text_categories": ["segredo", "segredo", "rh"]}, headers=admin).json()["omit_text_categories"] == ["rh", "segredo"]
    assert post(client, world, event(f"chave {SECRET}"))["masked_text"].startswith("[texto não guardado: categoria ")
    assert client.patch("/v1/tenant", json={"omit_text_categories": ["saude"]}, headers=world.user("analista")).status_code == 403
