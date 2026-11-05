"""Licenciamento on-premise (lado do cliente) contra o serviço de licenças REAL rodando em processo: ativação, renovação, os dois prazos,
os estados e o que cada um bloqueia. O relógio é injetado (nenhum teste espera tempo de verdade). Dados SINTÉTICOS."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from conftest import ADMIN_URL, event
from fastapi.testclient import TestClient
from promptshield_licensing import Installation, State, generate_signing_key, issue_authorization, public_key_b64
from promptshield_licensing.crypto import private_pem
from sqlalchemy import text

pytestmark = pytest.mark.db
LIC_DIR = Path(__file__).resolve().parents[2] / "licensing"
LIC_TABLES = "lic_nonces, lic_authorizations, lic_installations, lic_activation_codes, lic_contracts, lic_customers, lic_audit"


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.start = self.now

    def to(self, **delta) -> datetime:
        self.now = self.start + timedelta(**delta)
        return self.now


class Lic:
    """Cola entre o produto do cliente e o serviço de licenças do fornecedor (os dois no mesmo processo)."""

    def __init__(self, clock: Clock, vendor_key, tmp_path, factory_log: list) -> None:
        self.clock, self.vendor_key, self.dir, self.calls = clock, vendor_key, tmp_path, factory_log

    def new_code(self, devices=100, months=12, tolerance_days=15, on_end="stop_inspection", code_days=7) -> str:
        from lic_service import service
        from lic_service.db import session_scope

        with session_scope() as s:
            k = service.create_contract(s, service.create_customer(s, "Acme Ltda"), devices, months, tolerance_days=tolerance_days, on_end=on_end)
            self.contract_id = str(k.id)
            return service.issue_code(s, k, self.clock.now, code_days)

    def vendor(self, fn):
        from lic_service import service
        from lic_service.db import session_scope
        from lic_service.models import Contract

        with session_scope() as s:
            return fn(service, s, s.get(Contract, self.contract_id))


@pytest.fixture
def lic(world, admin_engine, tmp_path, monkeypatch):
    from lic_service import db as ldb
    from lic_service import main as lmain
    from lic_service import service as lsvc
    from lic_service.config import settings as lsettings

    from app import license_client
    from app.config import settings

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=LIC_DIR, env={**os.environ, "LICENSING_ADMIN_DATABASE_URL": ADMIN_URL}, check=True)
    vendor_key = generate_signing_key()
    clock, calls = Clock(), []
    lsettings.database_url, lsettings.rate_limit_per_minute = ADMIN_URL, 10_000
    lsettings.license_signing_key = base64.b64encode(private_pem(vendor_key)).decode()
    ldb.reset_engine()
    lmain.reset_limits()
    with admin_engine.begin() as c:
        c.execute(text(f"TRUNCATE {LIC_TABLES} CASCADE"))
        c.execute(text("TRUNCATE license_state"))
    monkeypatch.setattr(lsvc, "utcnow", lambda: clock.now)
    monkeypatch.setattr(license_client, "_now", lambda: clock.now)
    monkeypatch.setattr(settings, "license_mode", "onprem")
    monkeypatch.setattr(settings, "license_server_url", "http://testserver")
    monkeypatch.setattr(settings, "license_public_key", public_key_b64(vendor_key))
    monkeypatch.setattr(settings, "license_state_dir", str(tmp_path / "state"))
    monkeypatch.setattr(settings, "license_allow_http", True)
    monkeypatch.setattr(license_client, "http_factory", lambda: (calls.append(1), TestClient(lmain.app))[1])
    license_client.invalidate()
    yield Lic(clock, vendor_key, tmp_path, calls)
    license_client.invalidate()
    ldb.reset_engine()


class Stub:
    """Cliente HTTP falso: rede fora do ar, ou um servidor que responde o que quisermos."""

    def __init__(self, fn) -> None:
        self.fn = fn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, **kw):
        return self.fn(url, json)


def down(url, body):
    raise httpx.ConnectError("sem rede")


def admin(world):
    return world.user("admin")


def activate(client, world, lic, **kw):
    r = client.post("/v1/license/activate", json={"code": lic.new_code(**kw)}, headers=admin(world))
    assert r.status_code == 200, r.text
    return r.json()


def status(client, world):
    return client.get("/v1/license/status", headers=world.user("leitura")).json()


def ingest(client, world):
    return client.post("/v1/events", json=event("SIMULADO: oi"), headers=world.key())


# ---------- ativação ----------
def test_not_activated_blocks_inspection_but_lets_the_admin_read_and_activate(client, world, lic, tmp_path):
    st = status(client, world)
    assert (st["state"], st["inspecting"], st["can_enroll"]) == ("nao_ativado", False, False) and st["installation_id"] is None
    r = ingest(client, world)
    assert r.status_code == 403 and r.headers["x-promptshield-inspection"] == "stopped" and "ativação" in r.json()["detail"]
    assert client.get("/v1/events", headers=world.user("leitura")).status_code == 200                       # leitura sempre
    assert client.patch("/v1/tenant", json={"retention_days": 30}, headers=admin(world)).status_code == 403   # alteração não
    code = lic.new_code()
    assert client.post("/v1/license/activate", json={"code": code}, headers=world.user("analista")).status_code == 403
    r = client.post("/v1/license/activate", json={"code": code}, headers=admin(world))
    assert r.status_code == 200, r.text
    st = r.json()
    assert (st["state"], st["inspecting"], st["max_devices"], st["customer"], st["serial"]) == ("ativo", True, 100, "Acme Ltda", 1)
    assert st["installation_id"] and st["contract_end"] > st["auth_expires"] and st["on_end"] == "stop_inspection"
    assert ingest(client, world).status_code == 200
    pem = tmp_path / "state" / "installation.pem"
    assert pem.stat().st_mode & 0o777 == 0o600                                                           # chave privada só do dono
    stored = " ".join(map(str, world.sql("SELECT auth_token, installation_id FROM license_state").all()))
    assert "PRIVATE" not in stored                                                                       # a chave privada nunca vai ao banco
    again = client.post("/v1/license/activate", json={"code": code}, headers=admin(world))
    assert again.status_code == 400 and again.json()["detail"]["code"] == "code_used"
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'license.activate'").scalar() == 1
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'license.activate_failed'").scalar() == 1


def test_a_fake_license_server_cannot_activate_us(client, world, lic):
    """A chave pública do fornecedor está fixada: um servidor falso, mesmo com resposta bem formada, é recusado."""
    from app import license_client

    attacker = generate_signing_key()

    def fake(url, body):
        inst = license_client.installation()
        now = lic.clock.now
        token, _ = issue_authorization(attacker, license_id="x", installation_id=inst.installation_id, customer="Falso", max_devices=9999,
                                       contract_start=now, contract_end=now + timedelta(days=3650), tolerance_days=0, status="active",
                                       on_end="stop_inspection", serial=1, now=now, validity=timedelta(days=7))
        return httpx.Response(200, json={"authorization": token})

    license_client.http_factory = lambda: Stub(fake)
    r = client.post("/v1/license/activate", json={"code": "psa_00000000_qualquer-coisa"}, headers=admin(world))
    assert r.status_code == 502 and r.json()["detail"]["code"] == "bad_authorization"
    assert status(client, world)["state"] == "nao_ativado"


def test_unreachable_vendor_during_activation_is_a_clear_error(client, world, lic):
    from app import license_client

    license_client.http_factory = lambda: Stub(down)
    r = client.post("/v1/license/activate", json={"code": "psa_00000000_qualquer-coisa"}, headers=admin(world))
    assert r.status_code == 502 and r.json()["detail"]["code"] == "unreachable"


# ---------- renovação e falta de contato ----------
def test_daily_renewal_runs_only_when_due(client, world, lic):
    from app import license_client

    activate(client, world, lic)
    n = len(lic.calls)
    assert license_client.renew_if_due(lic.clock.to(hours=5)) == "em dia" and len(lic.calls) == n                 # sem tráfego à toa
    assert license_client.renew_if_due(lic.clock.to(hours=25)) == "renovado"
    st = status(client, world)
    assert st["serial"] == 2 and st["state"] == "ativo"
    assert license_client.renew_if_due(lic.clock.to(hours=26)) == "em dia"


def test_vendor_outage_keeps_working_warns_then_expires_without_stopping_inspection(client, world, lic):
    from app import license_client

    activate(client, world, lic)
    real = license_client.http_factory
    license_client.http_factory = lambda: Stub(down)
    assert license_client.renew_if_due(lic.clock.to(hours=25)) == "falhou:unreachable"
    assert license_client.renew_if_due(lic.clock.to(hours=25, minutes=5)) == "aguardando nova tentativa"       # sem martelar o serviço
    # 3 dias sem contato: avisa, tudo funciona
    lic.clock.to(days=3)
    license_client.invalidate()
    st = status(client, world)
    assert st["state"] == "sem_contato" and st["inspecting"] and st["can_enroll"] and st["last_attempt_failed"] and "unreachable" in st["last_error"]
    assert ingest(client, world).status_code == 200
    # a autorização local (7 dias) venceu: expirado => sem NOVAS matrículas; inspeção, consulta e alterações continuam
    lic.clock.to(days=8)
    license_client.invalidate()
    st = status(client, world)
    assert (st["state"], st["inspecting"], st["can_enroll"]) == ("expirado", True, False)
    assert ingest(client, world).status_code == 200
    assert client.get("/v1/events/export.csv", params={"days": 30}, headers=world.user("auditor")).status_code == 200
    tok = client.post("/v1/enrollment-tokens", json={"name": "t"}, headers=admin(world)).json()["token"]
    refused = client.post("/v1/enroll", json={"token": tok, "hostname": "NB-1", "os": "windows", "tools": []})
    assert refused.status_code == 403 and "licença" in refused.json()["detail"]
    # o serviço volta: renova e tudo normaliza
    license_client.http_factory = real
    assert license_client.renew_if_due(lic.clock.to(days=8, hours=1)) == "renovado"
    license_client.invalidate()
    assert status(client, world)["state"] == "ativo"
    assert client.post("/v1/enroll", json={"token": tok, "hostname": "NB-1", "os": "windows", "tools": []}).status_code == 201


# ---------- contrato vs autorização ----------
def test_contract_end_tolerance_and_expiry(client, world, lic):
    from app import license_client

    activate(client, world, lic, months=1, tolerance_days=10)
    end = datetime.fromisoformat(status(client, world)["contract_end"])
    lic.clock.now = end - timedelta(days=1)
    assert license_client.renew(lic.clock.now) and status(client, world)["state"] == "ativo"
    # contrato venceu: em tolerância (a autorização é cortada no fim da tolerância, nunca depois)
    lic.clock.now = end + timedelta(days=1)
    license_client.renew(lic.clock.now)
    license_client.invalidate()
    st = status(client, world)
    assert st["state"] == "em_tolerancia" and st["inspecting"] and st["can_enroll"] and st["days_left"] == 9
    assert datetime.fromisoformat(st["auth_expires"]) == end + timedelta(days=8)          # 7 dias a partir de hoje, ainda dentro da tolerância
    assert ingest(client, world).status_code == 200
    lic.clock.now = end + timedelta(days=9)
    license_client.renew(lic.clock.now)
    license_client.invalidate()
    assert datetime.fromisoformat(status(client, world)["auth_expires"]) == end + timedelta(days=10)   # cortada no fim da tolerância, nunca depois
    # depois da tolerância o serviço recusa renovar; a recusa aparece, e o estado vira expirado
    lic.clock.now = end + timedelta(days=11)
    with pytest.raises(license_client.LicenseError) as e:
        license_client.renew(lic.clock.now)
    assert e.value.code == "contract_expired"
    license_client.invalidate()
    st = status(client, world)
    assert st["state"] == "expirado" and st["inspecting"] and not st["can_enroll"] and "contract_expired" in st["last_error"] and not st["last_attempt_failed"]


def test_closed_contract_stop_inspection_policy_is_visible_and_reversible(client, world, lic):
    from app import license_client

    activate(client, world, lic)                                         # padrão: stop_inspection
    lic.vendor(lambda svc, s, k: svc.close_contract(s, k, "cancelado a pedido", lic.clock.now))
    license_client.renew(lic.clock.to(days=1))
    license_client.invalidate()
    st = status(client, world)
    assert (st["state"], st["inspecting"], st["can_enroll"]) == ("encerrado", False, False) and "PARADA" in st["message"]
    r = ingest(client, world)
    assert r.status_code == 403 and r.headers["x-promptshield-inspection"] == "stopped" and "PARADA" in r.json()["detail"]
    assert client.get("/v1/events", headers=world.user("leitura")).status_code == 200                         # consulta
    assert client.get("/v1/events/export.csv", params={"days": 30}, headers=world.user("auditor")).status_code == 200   # exportação
    assert client.patch("/v1/tenant", json={"retention_days": 30}, headers=admin(world)).status_code == 403
    assert world.sql("SELECT count(*) FROM events").scalar() == 0                                              # nada foi apagado nem gravado
    # reabrir no fornecedor e renovar (pelo botão do administrador, que continua permitido) restaura
    lic.vendor(lambda svc, s, k: svc.reopen_contract(s, k, lic.clock.now))
    assert client.post("/v1/license/renew", headers=admin(world)).status_code == 200
    assert status(client, world)["state"] == "ativo" and ingest(client, world).status_code == 200


def test_closed_contract_keep_inspection_policy(client, world, lic):
    from app import license_client

    activate(client, world, lic, on_end="keep_inspection")
    lic.vendor(lambda svc, s, k: svc.close_contract(s, k, "fim do contrato", lic.clock.now))
    license_client.renew(lic.clock.to(days=1))
    license_client.invalidate()
    st = status(client, world)
    assert (st["state"], st["inspecting"], st["can_enroll"]) == ("encerrado", True, False)
    assert ingest(client, world).status_code == 200


def test_device_limit_is_the_smaller_of_tenant_and_license(client, world, lic):
    activate(client, world, lic, devices=1)
    for host, expected in (("NB-1", 201), ("NB-2", 403)):
        tok = client.post("/v1/enrollment-tokens", json={"name": host}, headers=admin(world)).json()["token"]
        r = client.post("/v1/enroll", json={"token": tok, "hostname": host, "os": "windows", "tools": []})
        assert r.status_code == expected, r.text
    assert "limite" in r.json()["detail"]


# ---------- adulteração, repetição e relógio ----------
def test_tampered_or_replayed_authorizations_and_missing_identity_are_rejected(client, world, lic, tmp_path):
    from app import license_client

    activate(client, world, lic)
    license_client.renew(lic.clock.to(hours=25))                                                              # serial 2
    good = world.sql("SELECT auth_token FROM license_state").scalar()
    # reapresentar uma autorização antiga (serial 1) como se fosse a nova: recusada
    old_token = None

    def capture(url, body):
        return httpx.Response(200, json={"authorization": old_token})

    from lic_service.db import session_scope
    from lic_service.models import IssuedAuthorization  # noqa: F401  (só o hash fica guardado; reemito um serial 1 igual ao original)
    inst = license_client.installation()
    from promptshield_licensing import verify_authorization
    a = verify_authorization(good, lic.vendor_key.public_key(), inst.installation_id, lic.clock.now)
    old_token, _ = issue_authorization(lic.vendor_key, license_id=a.license_id, installation_id=a.installation_id, customer=a.customer,
                                       max_devices=a.max_devices, contract_start=a.contract_start, contract_end=a.contract_end,
                                       tolerance_days=a.tolerance_days, status="active", on_end=a.on_end, serial=1, now=lic.clock.now,
                                       validity=timedelta(days=7))
    real = license_client.http_factory
    license_client.http_factory = lambda: Stub(capture)
    with pytest.raises(license_client.LicenseError) as e:
        license_client.renew(lic.clock.to(hours=50))
    assert e.value.code == "bad_authorization" and "mais antiga" in e.value.detail
    license_client.http_factory = real
    del session_scope
    # adulterar o que está guardado (limite de máquinas) invalida a assinatura
    head, payload, sig = good.split(".")
    from promptshield_licensing import b64d, b64e
    forged = f"{head}.{b64e(b64d(payload).replace(b'\"max_devices\":100', b'\"max_devices\":999'))}.{sig}"
    world.sql("UPDATE license_state SET auth_token = :a", a=forged)
    license_client.invalidate()
    st = status(client, world)
    assert st["state"] == "nao_ativado" and "inválida" in st["message"] and ingest(client, world).status_code == 403
    world.sql("UPDATE license_state SET auth_token = :a", a=good)
    license_client.invalidate()
    assert status(client, world)["state"] == "ativo"
    # sem a identidade (chave privada) a autorização não vale para esta instalação
    (tmp_path / "state" / "installation.pem").unlink()
    license_client.invalidate()
    assert status(client, world)["state"] == "nao_ativado" and "identidade" in status(client, world)["message"]


def test_rolling_the_clock_back_does_not_resurrect_an_expired_license(client, world, lic):
    from app import license_client

    activate(client, world, lic)
    lic.clock.to(days=9)
    license_client.invalidate()
    assert license_client.state().state == State.EXPIRADO                      # grava o maior horário já visto
    lic.clock.to(days=1)                                                       # alguém volta o relógio do servidor
    license_client.invalidate()
    assert status(client, world)["state"] == "expirado"


def test_license_mode_off_changes_nothing(client, world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "license_mode", "off")
    assert client.get("/v1/license/status", headers=world.user("leitura")).json()["mode"] == "off"
    assert client.post("/v1/license/activate", json={"code": "x" * 12}, headers=world.user("admin")).status_code == 404
    assert ingest(client, world).status_code == 200
    assert client.patch("/v1/tenant", json={"retention_days": 45}, headers=world.user("admin")).status_code == 200
    _ = Installation
