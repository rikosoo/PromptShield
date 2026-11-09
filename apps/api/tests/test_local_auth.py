"""Login com e-mail e senha: política, troca obrigatória, bloqueio, sessões, senha temporária e sigilo. Dados SINTÉTICOS."""
import os
import subprocess
import sys

import pytest
from conftest import ADMIN_URL, API_DIR

from app import passwords, ratelimit
from app.config import settings

pytestmark = pytest.mark.db
STRONG = "Teste-PS-2026!"
NEW = "Outra-Senha#77"
EMAIL = "colab@a.example.com"


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    monkeypatch.setattr(settings, "local_auth", True)
    monkeypatch.setattr(settings, "local_auth_secret", "x" * 40)
    ratelimit.reset()
    yield
    ratelimit.reset()


def login(client, email=EMAIL, password=STRONG):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def make(client, world, **over):
    r = client.post("/v1/users", json={"email": EMAIL, "role": "analista", **over}, headers=world.user("admin"))
    assert r.status_code == 201, r.text
    return r.json()


def test_login_is_off_unless_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "local_auth", False)
    assert login(client).status_code == 404


def test_admin_creates_collaborator_with_generated_temporary_password_and_forced_change(client, world):
    created = make(client, world)
    temp = created["temporary_password"]
    assert passwords.policy_errors(temp) == [] and created["must_change_password"] is True
    r = login(client, password=temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    tok = r.json()["access_token"]
    # com senha provisória só /v1/me e a troca respondem
    me = client.get("/v1/me", headers=bearer(tok)).json()
    assert me["must_change_password"] is True and me["role"] == "analista" and me["email"] == EMAIL
    blocked = client.get("/v1/events", headers=bearer(tok))
    assert blocked.status_code == 403 and blocked.headers["X-PromptShield-Password-Change"] == "required"
    assert client.get("/v1/incidents", headers=bearer(tok)).status_code == 403
    # troca: política, senha atual, diferente da atual
    ch = lambda cur, new: client.post("/v1/me/password", json={"current_password": cur, "new_password": new}, headers=bearer(tok))   # noqa: E731
    weak = ch(temp, "123456")
    assert weak.status_code == 422 and "pelo menos 8" in weak.json()["detail"] and "maiúscula" in weak.json()["detail"]
    assert ch("senha errada", NEW).status_code == 422
    assert ch(temp, temp).status_code == 422
    ok = ch(temp, NEW)
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    new_tok = ok.json()["access_token"]
    assert client.get("/v1/events", headers=bearer(tok)).status_code == 401                    # a sessão antiga caiu
    assert client.get("/v1/events", headers=bearer(new_tok)).status_code == 200                # a nova funciona
    assert client.get("/v1/me", headers=bearer(new_tok)).json()["must_change_password"] is False
    assert login(client, password=temp).status_code == 401 and login(client, password=NEW).status_code == 200


def test_admin_can_set_the_initial_password_but_it_must_follow_the_policy(client, world):
    bad = client.post("/v1/users", json={"email": EMAIL, "role": "leitura", "password": "123456"}, headers=world.user("admin"))
    assert bad.status_code == 422 and "a senha precisa ter" in bad.json()["detail"]
    r = make(client, world, password=STRONG)
    assert "temporary_password" not in r and r["must_change_password"] is True            # o admin já sabe a senha; a pessoa é obrigada a trocar
    assert login(client, password=STRONG).json()["must_change_password"] is True


def test_every_failure_looks_the_same_so_nobody_learns_who_exists(client, world):
    make(client, world, password=STRONG)
    no_password = login(client, email="admin@a.example.com", password=STRONG)               # existe, mas nunca teve senha
    unknown = login(client, email="ninguem@a.example.com")
    wrong = login(client, password="Errada#123")
    assert {r.status_code for r in (no_password, unknown, wrong)} == {401}
    assert no_password.json() == unknown.json() == wrong.json()
    assert login(client, email="ninguem@a.example.com", password="").status_code == 422     # senha vazia nem chega à conferência


def test_lockout_after_repeated_failures_and_admin_reset_unlocks(client, world):
    make(client, world, password=STRONG)
    for _ in range(settings.login_max_failures):
        assert login(client, password="Errada#123").status_code == 401
    locked = login(client, password=STRONG)                                                  # senha CERTA, mas bloqueado
    assert locked.status_code == 401 and locked.json() == login(client, password="Errada#123").json()
    row = next(u for u in client.get("/v1/users", headers=world.user("admin")).json() if u["email"] == EMAIL)
    assert row["locked"] is True
    reset = client.post(f"/v1/users/{row['id']}/password", headers=world.user("admin"))
    assert reset.status_code == 200
    assert login(client, password=reset.json()["temporary_password"]).status_code == 200      # a nova temporária desbloqueia
    assert next(u for u in client.get("/v1/users", headers=world.user("admin")).json() if u["email"] == EMAIL)["locked"] is False


def test_lock_expires_by_itself(client, world):
    make(client, world, password=STRONG)
    for _ in range(settings.login_max_failures):
        login(client, password="Errada#123")
    assert login(client).status_code == 401
    world.sql("UPDATE users SET locked_until = now() - interval '1 minute' WHERE lower(email) = :e", e=EMAIL)
    assert login(client).status_code == 200


def test_success_resets_the_failure_counter(client, world):
    make(client, world, password=STRONG)
    for _ in range(settings.login_max_failures - 1):
        login(client, password="Errada#123")
    assert login(client).status_code == 200
    for _ in range(settings.login_max_failures - 1):
        login(client, password="Errada#123")
    assert login(client).status_code == 200                                                  # nunca chegou ao limite seguido


def test_admin_reset_rules_and_it_ends_open_sessions(client, world):
    created = make(client, world, password=STRONG)
    tok = login(client).json()["access_token"]
    url = f"/v1/users/{created['id']}/password"
    for who in ("analista", "auditor", "leitura"):
        assert client.post(url, headers=world.user(who)).status_code == 403
    me = next(u for u in client.get("/v1/users", headers=world.user("admin")).json() if u["is_me"])
    assert client.post(f"/v1/users/{me['id']}/password", headers=world.user("admin")).status_code == 409      # a própria senha: pelo «Alterar senha»
    assert client.post("/v1/users/00000000-0000-0000-0000-000000000000/password", headers=world.user("admin")).status_code == 404
    r = client.post(url, headers=world.user("admin"))
    assert r.status_code == 200 and passwords.policy_errors(r.json()["temporary_password"]) == []
    assert client.get("/v1/me", headers=bearer(tok)).status_code == 401                      # sessões abertas caem
    assert login(client, password=STRONG).status_code == 401
    assert login(client, password=r.json()["temporary_password"]).json()["must_change_password"] is True


def test_deactivated_collaborator_loses_the_session_and_cannot_log_in(client, world):
    created = make(client, world, password=STRONG)
    tok = login(client).json()["access_token"]
    client.patch(f"/v1/users/{created['id']}", json={"active": False}, headers=world.user("admin"))
    assert client.get("/v1/me", headers=bearer(tok)).status_code == 401 and login(client).status_code == 401


def test_password_is_never_stored_or_logged_in_clear(client, world):
    temp = make(client, world)["temporary_password"]
    stored = world.sql("SELECT password_hash FROM users WHERE lower(email) = :e", e=EMAIL).scalar()
    assert stored.startswith("scrypt$") and temp not in stored
    assert world.sql("SELECT count(*) FROM audit_log WHERE detail::text LIKE :p", p=f"%{temp}%").scalar() == 0
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'user.create' AND detail::text LIKE '%password_set%'").scalar() == 1
    tok = login(client, password=temp).json()["access_token"]
    client.post("/v1/me/password", json={"current_password": temp, "new_password": NEW}, headers=bearer(tok))
    assert world.sql("SELECT count(*) FROM audit_log WHERE detail::text LIKE :p", p=f"%{NEW}%").scalar() == 0
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'user.password_change'").scalar() == 1


def test_wrong_current_password_counts_toward_the_lock(client, world):
    make(client, world, password=STRONG)
    tok = login(client).json()["access_token"]
    for _ in range(settings.login_max_failures):
        client.post("/v1/me/password", json={"current_password": "Errada#123", "new_password": NEW}, headers=bearer(tok))
    r = client.post("/v1/me/password", json={"current_password": STRONG, "new_password": NEW}, headers=bearer(tok))
    assert r.status_code == 429


def test_tampered_or_foreign_tokens_are_refused_and_mock_tokens_still_work(client, world):
    make(client, world, password=STRONG)
    import jwt as pyjwt
    forged = pyjwt.encode({"iss": "promptshield-local", "aud": "promptshield-console", "sub": "x", "email": EMAIL, "email_verified": True, "pv": 1,
                           "exp": 4102444800}, "outra-chave-com-mais-de-trinta-e-dois-caracteres", algorithm="HS256")
    assert client.get("/v1/me", headers=bearer(forged)).status_code == 401
    assert client.get("/v1/me", headers=world.user("admin")).status_code == 200              # o login simulado (OIDC mock) segue funcionando


def test_rate_limit_per_email(client, world):
    make(client, world, password=STRONG)
    codes = {login(client, email="spam@a.example.com", password="Qualquer#1").status_code for _ in range(settings.login_per_email_per_minute + 3)}
    assert 429 in codes and 401 in codes


def test_cli_set_password_generates_a_temporary_one_and_the_admin_can_log_in(client, world):
    env = {**os.environ, "ADMIN_DATABASE_URL": ADMIN_URL}
    out = subprocess.run([sys.executable, "-m", "app.cli", "set-password", "--email", "admin@a.example.com", "--generate"],
                         cwd=API_DIR, env=env, capture_output=True, text=True, check=True).stdout
    temp = out.split(": ")[-1].strip()
    assert passwords.policy_errors(temp) == []
    r = login(client, email="admin@a.example.com", password=temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert subprocess.run([sys.executable, "-m", "app.cli", "set-password", "--email", "nao.existe@a.example.com", "--generate"],
                          cwd=API_DIR, env=env, capture_output=True, text=True).returncode != 0
