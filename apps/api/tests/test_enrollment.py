"""Matrícula de dispositivos: token revogável -> chave própria por máquina. Dados sintéticos; sem máquina real."""
import pytest
from conftest import event

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    from app import ratelimit
    ratelimit.reset()


def make_token(client, world, **body):
    r = client.post("/v1/enrollment-tokens", json={"name": "piloto", **body}, headers=world.user("admin"))
    assert r.status_code == 201, r.text
    return r.json()


def enroll(client, token, host="NOTE-01", tools=("claude_code",)):
    return client.post("/v1/enroll", json={"token": token, "hostname": host, "os": "windows", "client_version": "0.1", "tools": list(tools)})


def test_token_becomes_a_device_key_that_ingests_and_can_be_revoked(client, world):
    t = make_token(client, world)
    assert t["token"].startswith("pse_") and "token_hash" not in t
    r = enroll(client, t["token"])
    assert r.status_code == 201
    key = r.json()["api_key"]
    assert key.startswith("ps_") and key != world.a["api_key"]
    assert client.post("/v1/events", json=event("SIMULADO oi"), headers={"X-API-Key": key}).status_code == 200
    d = client.get("/v1/devices", headers=world.user("leitura")).json()
    assert d["active"] == 1 and d["coverage"] == {"claude_code": 1} and d["devices"][0]["hostname"] == "NOTE-01"
    assert d["devices"][0]["last_seen_at"] is not None
    assert client.post(f"/v1/devices/{d['devices'][0]['id']}/revoke", headers=world.user("admin")).status_code == 200
    assert client.post("/v1/events", json=event("SIMULADO depois"), headers={"X-API-Key": key}).status_code == 401   # só esta máquina caiu
    assert client.post("/v1/events", json=event("SIMULADO ok"), headers=world.key()).status_code == 200
    assert client.get("/v1/devices", headers=world.user("leitura")).json()["active"] == 0


def test_revoked_expired_exhausted_and_unknown_tokens_are_refused_equally(client, world):
    rev = make_token(client, world)
    assert client.post(f"/v1/enrollment-tokens/{rev['id']}/revoke", headers=world.user("admin")).status_code == 200
    exp = make_token(client, world)
    world.sql("UPDATE enrollment_tokens SET expires_at = now() - interval '1 minute' WHERE id = :i", i=exp["id"])
    one = make_token(client, world, max_uses=1)
    assert enroll(client, one["token"]).status_code == 201
    msgs = set()
    for tok in (rev["token"], exp["token"], one["token"], "pse_00000000_inexistente-inexistente"):
        r = enroll(client, tok, host="X")
        assert r.status_code == 401
        msgs.add(r.json()["detail"])
    assert len(msgs) == 1                                   # mesma resposta: nada ajuda quem adivinha
    st = {t["name"]: t["status"] for t in client.get("/v1/enrollment-tokens", headers=world.user("admin")).json()}
    assert "piloto" in st


def test_only_admin_manages_tokens_and_tenants_are_isolated(client, world):
    assert client.post("/v1/enrollment-tokens", json={"name": "x"}, headers=world.user("analista")).status_code == 403
    t = make_token(client, world)
    enroll(client, t["token"])
    other = world.tok("admin@b.example.com")
    assert client.get("/v1/devices", headers=other).json()["devices"] == []
    assert client.get("/v1/enrollment-tokens", headers=other).json() == []
    dev_id = client.get("/v1/devices", headers=world.user("admin")).json()["devices"][0]["id"]
    assert client.post(f"/v1/devices/{dev_id}/revoke", headers=other).status_code == 404
    # o token é do tenant A: a chave que ele gera só enxerga o tenant A
    key = enroll(client, t["token"], host="NOTE-02").json()["api_key"]
    client.post("/v1/events", json=event("SIMULADO A"), headers={"X-API-Key": key})
    assert client.get("/v1/events", headers=other).json() == []


def test_enroll_validation_and_audit(client, world):
    assert client.post("/v1/enroll", json={}).status_code == 422
    t = make_token(client, world)
    assert client.post("/v1/enroll", json={"token": t["token"], "hostname": "A", "extra": 1}).status_code == 422
    enroll(client, t["token"], host="AUDITADO")
    acts = {a["action"] for a in client.get("/v1/audit-log", headers=world.user("auditor")).json()}
    assert {"enrollment_token.create", "device.enroll"} <= acts


# ---------- licença: limite de máquinas ativas (45 dias), validade, reinstalação, concorrência ----------
import hashlib  # noqa: E402
import threading  # noqa: E402


def set_license(world, tenant="a", max_devices=None, expires=None):
    world.sql("UPDATE tenants SET max_devices = :m, license_expires_at = :e WHERE id = :t", m=max_devices, e=expires, t=world.a["tenant_id"] if tenant == "a" else world.b["tenant_id"])


def mh(name):
    return hashlib.sha256(name.encode()).hexdigest()


def enroll_m(client, token, host, machine=None):
    body = {"token": token, "hostname": host, "tools": ["claude_code"]}
    if machine:
        body["machine_id_hash"] = mh(machine)
    return client.post("/v1/enroll", json=body)


def test_limit_blocks_only_new_machines_and_does_not_burn_the_token(client, world):
    set_license(world, max_devices=2)
    t = make_token(client, world, max_uses=10)
    keys = [enroll_m(client, t["token"], f"PC-{i}").json().get("api_key") for i in range(2)]
    assert all(k and k.startswith("ps_") for k in keys)
    r = enroll_m(client, t["token"], "PC-3")
    assert r.status_code == 403 and "limite de máquinas" in r.json()["detail"] and "2 de 2" in r.json()["detail"]
    uses = {x["name"]: x["uses"] for x in client.get("/v1/enrollment-tokens", headers=world.user("admin")).json()}
    assert uses["piloto"] == 2                                              # a recusa desfez o uso do token
    # quem já está instalado continua enviando, mesmo no limite
    assert client.post("/v1/events", json=event("SIMULADO ainda envia"), headers={"X-API-Key": keys[0]}).status_code == 200
    lic = client.get("/v1/devices", headers=world.user("leitura")).json()["license"]
    assert lic["max_devices"] == 2 and lic["active_seats"] == 2 and lic["level"] == "esgotada" and lic["window_days"] == 45
    acts = [a["action"] for a in client.get("/v1/audit-log", headers=world.user("auditor")).json()]
    assert "device.enroll_refused" in acts
    # revogar libera a vaga
    dev = client.get("/v1/devices", headers=world.user("admin")).json()["devices"][0]
    client.post(f"/v1/devices/{dev['id']}/revoke", headers=world.user("admin"))
    assert enroll_m(client, t["token"], "PC-3").status_code == 201


def test_only_machines_active_in_the_last_45_days_count(client, world):
    set_license(world, max_devices=1)
    t = make_token(client, world)
    assert enroll_m(client, t["token"], "VELHO").status_code == 201
    assert enroll_m(client, t["token"], "NOVO").status_code == 403
    world.sql("UPDATE devices SET enrolled_at = now() - interval '46 days'")
    world.sql("UPDATE api_keys SET last_used_at = now() - interval '46 days' WHERE name LIKE 'dispositivo:%'")
    d = client.get("/v1/devices", headers=world.user("leitura")).json()
    assert d["license"]["active_seats"] == 0 and d["devices"][0]["counts_toward_license"] is False   # aposentado: não ocupa vaga
    assert enroll_m(client, t["token"], "NOVO").status_code == 201
    world.sql("UPDATE api_keys SET last_used_at = now() - interval '44 days' WHERE name = 'dispositivo:VELHO'")
    world.sql("UPDATE devices SET enrolled_at = now() - interval '44 days' WHERE hostname = 'VELHO'")
    assert client.get("/v1/devices", headers=world.user("leitura")).json()["license"]["active_seats"] == 2   # 44 dias ainda conta


def test_reinstalling_on_the_same_machine_reuses_the_seat(client, world):
    set_license(world, max_devices=1)
    t = make_token(client, world, max_uses=10)
    first = enroll_m(client, t["token"], "PC-A", machine="guid-1").json()["api_key"]
    second = enroll_m(client, t["token"], "PC-A", machine="guid-1")
    assert second.status_code == 201                                             # mesma máquina: não gasta outra vaga
    assert client.post("/v1/events", json=event("SIMULADO"), headers={"X-API-Key": first}).status_code == 401   # a chave antiga morreu
    assert client.post("/v1/events", json=event("SIMULADO"), headers={"X-API-Key": second.json()["api_key"]}).status_code == 200
    assert enroll_m(client, t["token"], "PC-B", machine="guid-2").status_code == 403   # outra máquina: sem vaga
    d = client.get("/v1/devices", headers=world.user("leitura")).json()
    assert d["active"] == 1 and d["license"]["active_seats"] == 1


def test_expired_license_blocks_new_enrollments_but_not_ingestion(client, world):
    t = make_token(client, world, max_uses=10)
    key = enroll_m(client, t["token"], "PC-1").json()["api_key"]
    set_license(world, max_devices=None, expires="2020-01-01T00:00:00+00:00")
    r = enroll_m(client, t["token"], "PC-2")
    assert r.status_code == 403 and "expirou" in r.json()["detail"]
    assert client.post("/v1/events", json=event("SIMULADO"), headers={"X-API-Key": key}).status_code == 200
    assert client.get("/v1/devices", headers=world.user("leitura")).json()["license"]["expired"] is True


def test_parallel_mass_enrollment_never_exceeds_the_limit(client, world):
    set_license(world, max_devices=3)
    t = make_token(client, world, max_uses=100)
    codes: list[int] = []

    def go(i):
        codes.append(enroll_m(client, t["token"], f"PC-{i}").status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    assert sorted(codes).count(201) == 3 and codes.count(403) == 5
    assert client.get("/v1/devices", headers=world.user("leitura")).json()["license"]["active_seats"] == 3


def test_company_admin_cannot_change_the_license(client, world):
    set_license(world, max_devices=5)
    for field in ({"max_devices": 9999}, {"license_expires_at": "2099-01-01T00:00:00Z"}):
        assert client.patch("/v1/tenant", json=field, headers=world.user("admin")).status_code == 422
    assert world.sql("SELECT max_devices FROM tenants WHERE id = :t", t=world.a["tenant_id"]).scalar() == 5
    # a licença de uma empresa não afeta a outra
    set_license(world, tenant="b", max_devices=0)
    t = make_token(client, world)
    assert enroll_m(client, t["token"], "PC-1").status_code == 201


def test_vendor_cli_sets_and_clears_the_license(client, world):
    import os
    import subprocess
    import sys

    from conftest import ADMIN_URL
    env = {**os.environ, "ADMIN_DATABASE_URL": ADMIN_URL}

    def cli(*args):
        p = subprocess.run([sys.executable, "-m", "app.cli", "set-license", "--slug", "empresa-a", *args], capture_output=True, text=True, env=env, timeout=60)
        assert p.returncode == 0, p.stderr
        return p.stdout

    assert "'max_devices': 50" in cli("--max-devices", "50", "--expires", "2099-12-31")
    row = world.sql("SELECT max_devices, license_expires_at FROM tenants WHERE slug = 'empresa-a'").one()
    assert row.max_devices == 50 and row.license_expires_at.year == 2100 and row.license_expires_at.month == 1   # fim do dia 31/12
    lic = client.get("/v1/devices", headers=world.user("leitura")).json()["license"]
    assert lic["max_devices"] == 50 and lic["expired"] is False and lic["expires_at"]
    assert "'max_devices': None" in cli("--unlimited", "--no-expiry")
    bad = subprocess.run([sys.executable, "-m", "app.cli", "set-license", "--slug", "nao-existe", "--max-devices", "1"], capture_output=True, text=True, env=env)
    assert bad.returncode != 0 and "não encontrada" in bad.stderr
