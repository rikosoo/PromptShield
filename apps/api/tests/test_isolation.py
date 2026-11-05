"""Prova de isolamento: o tenant A não vê nem altera dados do B, inclusive por SQL direto com o papel da aplicação."""
import uuid

import pytest
from conftest import event
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

pytestmark = pytest.mark.db


def _ingest_both(client, world):
    ra = client.post("/v1/events", json=event("CPF 529.982.247-25"), headers=world.key("a"))
    rb = client.post("/v1/events", json=event("segredo AKIAZ7QW4XK2M9PLR3TN"), headers=world.key("b"))
    assert ra.status_code == 200 and rb.status_code == 200
    return ra.json()["event_id"], rb.json()["event_id"]


def _app_conn(app_url, tenant: str | None):
    eng = create_engine(app_url)
    conn = eng.connect()
    tx = conn.begin()
    if tenant:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
    return eng, conn, tx


def test_direct_sql_with_app_role_only_sees_own_tenant(client, world, app_url):
    _ingest_both(client, world)
    a, b = world.a["tenant_id"], world.b["tenant_id"]
    eng, conn, tx = _app_conn(app_url, a)
    try:
        for table in ("events", "analyses", "incidents", "users", "api_keys", "policies", "audit_log"):
            tenants = {str(r[0]) for r in conn.execute(text(f"SELECT DISTINCT tenant_id FROM {table}"))}
            assert tenants <= {a}, f"{table} vazou {tenants - {a}}"
        assert conn.execute(text("SELECT count(*) FROM events")).scalar() == 1
        # tentativa explícita de ler o outro tenant
        assert conn.execute(text("SELECT count(*) FROM events WHERE tenant_id = :b"), {"b": b}).scalar() == 0
        assert {str(r[0]) for r in conn.execute(text("SELECT id FROM tenants"))} == {a}
        # não consegue alterar nem apagar linhas do outro tenant
        assert conn.execute(text("UPDATE events SET masked_text = 'x' WHERE tenant_id = :b"), {"b": b}).rowcount == 0
        assert conn.execute(text("DELETE FROM events WHERE tenant_id = :b"), {"b": b}).rowcount == 0
    finally:
        tx.rollback()
        conn.close()
        eng.dispose()


def test_insert_for_another_tenant_is_rejected(world, app_url):
    a, b = world.a["tenant_id"], world.b["tenant_id"]
    eng, conn, tx = _app_conn(app_url, a)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            conn.execute(text("INSERT INTO audit_log (tenant_id, actor_type, actor_id, action) VALUES (:t,'user','x','x')"), {"t": b})
    finally:
        tx.rollback()
        conn.close()
        eng.dispose()


def test_without_tenant_context_nothing_is_visible(client, world, app_url):
    _ingest_both(client, world)
    eng, conn, tx = _app_conn(app_url, None)
    try:
        for table in ("events", "users", "policies", "api_keys", "tenants"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    finally:
        tx.rollback()
        conn.close()
        eng.dispose()


def test_app_role_cannot_bypass_rls(app_url):
    eng, conn, tx = _app_conn(app_url, None)
    try:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert row == (False, False)
    finally:
        tx.rollback()
        conn.close()
        eng.dispose()


def test_api_does_not_leak_across_tenants(client, world):
    ea, eb = _ingest_both(client, world)
    # usuário do tenant A pede o evento do B pela API: não existe para ele
    assert client.get(f"/v1/events/{eb}", headers=world.user("leitura")).status_code == 404
    assert client.get(f"/v1/events/{ea}", headers=world.user("leitura")).status_code == 200
    listed = client.get("/v1/events", headers=world.user("leitura")).json()
    assert {e["event_id"] for e in listed} == {ea}
    assert len(client.get("/v1/incidents", headers=world.user("leitura")).json()) <= 1


def test_audit_log_is_append_only_even_for_app_role(client, world, app_url):
    client.post("/v1/policies", json={"name": "x", "action": "alert"}, headers=world.user("admin"))
    eng, conn, tx = _app_conn(app_url, world.a["tenant_id"])
    try:
        assert conn.execute(text("SELECT count(*) FROM audit_log")).scalar() >= 1
        with pytest.raises((DBAPIError, ProgrammingError)):
            conn.execute(text("UPDATE audit_log SET action = 'forjado'"))
    finally:
        tx.rollback()
        conn.close()
        eng.dispose()
    # nem o dono consegue apagar ou editar linhas
    with pytest.raises((DBAPIError, ProgrammingError)):
        world.sql("DELETE FROM audit_log WHERE tenant_id = :t", t=uuid.UUID(world.a["tenant_id"]))
