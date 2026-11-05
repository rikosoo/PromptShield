"""Suspensão reversível de uma empresa: o que para, o que continua e que nada é apagado. Dados SINTÉTICOS."""
import pytest
from conftest import event

from app.cli import set_suspension

pytestmark = pytest.mark.db


def suspend(world, who="a", reason="fatura em atraso", on=True):
    from sqlalchemy.orm import Session
    slug = "empresa-a" if who == "a" else "empresa-b"
    with Session(world.engine) as s, s.begin():
        return set_suspension(s, slug, on, reason)


def test_suspended_company_stops_collecting_but_keeps_reading(client, world):
    ev = event("SIMULADO: antes da suspensão")
    assert client.post("/v1/events", json=ev, headers=world.key()).status_code == 200
    out = suspend(world)
    assert out["suspended"] and out["reason"] == "fatura em atraso"

    r = client.post("/v1/events", json=event("SIMULADO: depois"), headers=world.key())
    assert r.status_code == 403 and "suspenso" in r.json()["detail"] and r.headers["x-promptshield-suspended"] == "1"
    assert client.get("/v1/hook-config", headers=world.key()).status_code == 403          # coletor: tudo recusado
    # console: lê e exporta, mas não altera
    for role in ("admin", "analista", "auditor", "leitura"):
        assert client.get("/v1/events", params={"days": 365}, headers=world.user(role)).status_code == 200
    assert client.get("/v1/events/export.csv", params={"days": 365}, headers=world.user("auditor")).status_code == 200
    assert client.patch("/v1/tenant", json={"retention_days": 30}, headers=world.user("admin")).status_code == 403
    assert client.post(f"/v1/events/{ev['event_id']}/feedback", json={"verdict": "correta"}, headers=world.user("analista")).status_code == 403
    tenant = client.get("/v1/tenant", headers=world.user("leitura")).json()["contract"]
    assert tenant["suspended"] is True and tenant["suspended_reason"] == "fatura em atraso" and tenant["suspended_at"]
    # nada foi apagado
    assert world.sql("SELECT count(*) FROM events WHERE tenant_id = :t", t=world.a["tenant_id"]).scalar() == 1
    # a outra empresa não foi afetada
    assert client.post("/v1/events", json=event("SIMULADO: outra empresa"), headers=world.key("b")).status_code == 200
    assert client.get("/v1/tenant", headers=world.user("admin", "b")).json()["contract"]["suspended"] is False


def test_resume_restores_everything_and_both_steps_are_audited(client, world):
    suspend(world)
    assert client.post("/v1/events", json=event("SIMULADO: x"), headers=world.key()).status_code == 403
    out = suspend(world, on=False)
    assert out["was_suspended"] and not out["suspended"]
    assert client.post("/v1/events", json=event("SIMULADO: voltou"), headers=world.key()).status_code == 200
    assert client.patch("/v1/tenant", json={"retention_days": 45}, headers=world.user("admin")).status_code == 200
    rows = world.sql("SELECT action, actor_type, actor_id FROM audit_log WHERE action IN ('tenant.suspend','tenant.resume') ORDER BY id").all()
    assert [(r.action, r.actor_type, r.actor_id) for r in rows] == [("tenant.suspend", "system", "fornecedor"), ("tenant.resume", "system", "fornecedor")]
    # suspender duas vezes não muda o "desde quando"
    suspend(world)
    first = world.sql("SELECT suspended_at FROM tenants WHERE id = :t", t=world.a["tenant_id"]).scalar()
    suspend(world, reason="outro texto")
    assert world.sql("SELECT suspended_at FROM tenants WHERE id = :t", t=world.a["tenant_id"]).scalar() == first


def test_enrollment_and_scheduled_reports_are_refused_while_suspended(client, world):
    tok = client.post("/v1/enrollment-tokens", json={"name": "t", "expires_in_days": 7}, headers=world.user("admin")).json()["token"]
    suspend(world)
    body = {"token": tok, "hostname": "NB-1", "os": "windows", "client_version": "0.1", "tools": []}
    r = client.post("/v1/enroll", json=body)
    assert r.status_code == 403 and "suspenso" in r.json()["detail"]
    suspend(world, on=False)
    assert client.post("/v1/enroll", json=body).status_code == 201                        # o token não foi gasto pela recusa
    suspend(world)
    from app import worker
    assert worker.run_schedules(world.a["tenant_id"]) == 0


def test_contract_notice_data_for_expiring_license(client, world):
    from datetime import datetime, timedelta, timezone
    world.sql("UPDATE tenants SET license_expires_at = :d WHERE id = :t", d=datetime.now(timezone.utc) + timedelta(days=9, hours=1), t=world.a["tenant_id"])
    c = client.get("/v1/tenant", headers=world.user("leitura")).json()["contract"]
    assert c["suspended"] is False and c["days_to_expiry"] == 9 and c["expired"] is False
    world.sql("UPDATE tenants SET license_expires_at = :d WHERE id = :t", d=datetime.now(timezone.utc) - timedelta(days=1), t=world.a["tenant_id"])
    assert client.get("/v1/tenant", headers=world.user("leitura")).json()["contract"]["expired"] is True
