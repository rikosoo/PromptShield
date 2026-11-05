"""API HTTP do serviço de licenças e CLI do fornecedor."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from promptshield_licensing import Installation, build_request, fingerprint, public_key_b64, verify_authorization
from sqlalchemy import text

from lic_service import cli, service
from lic_service.config import settings
from lic_service.db import session_scope
from lic_service.main import app, reset_limits

pytestmark = pytest.mark.db


@pytest.fixture
def client():
    return TestClient(app)


def new_code():
    with session_scope() as s:
        k = service.create_contract(s, service.create_customer(s, "Beta SA"), 50, 12)
        return service.issue_code(s, k, service.utcnow())


def now():
    return service.utcnow()


def test_public_key_is_served_and_matches_the_signing_key(client, vendor_key):
    r = client.get("/v1/public-key")
    assert r.status_code == 200 and r.json()["public_key"] == public_key_b64(vendor_key) and r.json()["key_id"] == fingerprint(public_key_b64(vendor_key))
    assert "private" not in r.text.lower()


def test_activate_and_renew_over_http(client, vendor_key):
    code, inst = new_code(), Installation.create()
    r = client.post("/v1/activate", json={"request": build_request(inst, "activate", now(), code=code, hostname="srv")})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    a = verify_authorization(r.json()["authorization"], vendor_key.public_key(), inst.installation_id, now())
    assert a.max_devices == 50 and a.status == "active"
    r2 = client.post("/v1/renew", json={"request": build_request(inst, "renew", now(), device_count=3)})
    assert r2.status_code == 200 and verify_authorization(r2.json()["authorization"], vendor_key.public_key(), inst.installation_id, now()).serial == 2


def test_errors_are_stable_codes_and_refusals_are_audited(client):
    inst = Installation.create()
    r = client.post("/v1/activate", json={"request": build_request(inst, "activate", now(), code="psa_00000000_errado")})
    assert r.status_code == 400 and r.json()["code"] == "invalid_code"
    assert client.post("/v1/renew", json={"request": build_request(inst, "renew", now())}).json()["code"] == "unknown_installation"
    assert client.post("/v1/activate", json={"request": "curto"}).status_code == 422           # validação do corpo
    assert client.post("/v1/activate", json={}).status_code == 422
    with session_scope() as s:
        rows = s.execute(text("SELECT action, detail->>'code' FROM lic_audit ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [("activate.refused", "invalid_code"), ("renew.refused", "unknown_installation")]


def test_rate_limit_per_ip_and_missing_signing_key(client, vendor_key):
    settings.rate_limit_per_minute = 3
    reset_limits()
    codes = [client.post("/v1/activate", json={"request": build_request(Installation.create(), "activate", now(), code="psa_00000000_x")}).status_code
             for _ in range(5)]
    assert codes == [400, 400, 400, 429, 429]
    settings.rate_limit_per_minute = 1000
    keep, settings.license_signing_key = settings.license_signing_key, None
    try:
        assert client.get("/v1/public-key").status_code == 503
        assert client.post("/v1/renew", json={"request": "x" * 30}).status_code == 503
    finally:
        settings.license_signing_key = keep


def test_cli_end_to_end(capsys, vendor_key):
    cli.main(["create-customer", "--name", "Gama Ltda"])
    cust = capsys.readouterr().out.split()[-1]
    cli.main(["create-contract", "--customer", cust, "--devices", "100", "--months", "12", "--on-end", "keep_inspection"])
    cid = capsys.readouterr().out.split()[1]
    cli.main(["issue-code", "--contract", cid, "--days", "3"])
    out = capsys.readouterr().out
    code = out.strip().splitlines()[-1]
    assert code.startswith("psa_") and "uso único" in out
    cli.main(["contracts"])
    assert "pendente" in capsys.readouterr().out
    inst = Installation.create()
    with session_scope() as s:
        service.activate(s, vendor_key, build_request(inst, "activate", now(), code=code), now())
    cli.main(["show", "--contract", cid])
    shown = capsys.readouterr().out
    assert "ativo" in shown and "USADO" in shown and "ATIVA" in shown and "keep_inspection" in shown and code not in shown
    cli.main(["close", "--contract", cid, "--reason", "cancelado"])
    cli.main(["audit", "--contract", cid])
    assert "contract.close" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["show", "--contract", "nao-e-um-uuid"])
