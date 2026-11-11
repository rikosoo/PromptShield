"""Limite compartilhado entre processos (banco) e IP de origem atrás de proxy. Dados SINTÉTICOS."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app import ratelimit
from app.clientip import client_ip
from app.config import settings

pytestmark = pytest.mark.db


def req(peer="10.0.0.9", xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


# ---------------------------------------------------------------- IP de origem
def test_forwarded_header_is_ignored_unless_proxies_are_configured():
    r = req(xff="1.2.3.4")
    assert client_ip(r, hops=0) == "10.0.0.9"                               # padrão seguro: quem fala direto não escolhe o próprio IP


def test_with_trusted_proxies_the_nth_entry_from_the_right_counts_and_a_forged_left_part_is_ignored():
    forged = req(xff="6.6.6.6, 203.0.113.7")                                # o cliente forjou 6.6.6.6; o NOSSO proxy acrescentou o IP real à direita
    assert client_ip(forged, hops=1) == "203.0.113.7"
    assert client_ip(req(xff="198.51.100.2, 203.0.113.7"), hops=2) == "198.51.100.2"
    assert client_ip(req(xff="2001:db8::1"), hops=1) == "2001:db8::1"


@pytest.mark.parametrize("xff", ["", "lixo", "999.1.1.1", "1.2.3.4; DROP TABLE x"])
def test_bad_or_missing_header_falls_back_to_the_connection_address(xff):
    assert client_ip(req(xff=xff), hops=1) == "10.0.0.9"


def test_fewer_entries_than_trusted_hops_falls_back():
    assert client_ip(req(xff="203.0.113.7"), hops=2) == "10.0.0.9"          # o cabeçalho não passou por todos os proxies esperados: não confia


# ---------------------------------------------------------------- compartilhado entre processos
def test_shared_limit_holds_even_when_each_process_has_its_own_memory():
    t = 1_000_000.0
    got = []
    for _ in range(5):
        ratelimit.reset()                                                   # simula OUTRO processo: memória vazia a cada chamada
        got.append(ratelimit.check_shared("k:a", 3, now=t))
    assert got[:3] == [None, None, None] and got[3] is not None and got[4] is not None
    assert 1 <= got[3] <= 61
    ratelimit.reset()
    assert ratelimit.check("k:a", 3, now=t) is None                         # a versão em memória, essa sim, seria furada com vários processos (o motivo desta mudança)


def test_shared_limit_resets_in_the_next_minute_and_keys_are_independent():
    t = 2_000_000.0
    assert [ratelimit.check_shared("k:b", 1, now=t) for _ in range(2)][1] is not None
    assert ratelimit.check_shared("k:c", 1, now=t) is None                  # outra chave: não é afetada
    assert ratelimit.check_shared("k:b", 1, now=t + 61) is None             # janela nova


def test_shared_limit_stores_only_a_hash_never_the_email_or_ip(admin_engine):
    from sqlalchemy import text

    ratelimit.check_shared("login:pessoa@exemplo.test", 5)
    ratelimit.check_shared("login:ip:203.0.113.7", 5)
    with admin_engine.begin() as c:
        keys = [r[0] for r in c.execute(text("SELECT key FROM rate_hits")).all()]
    assert len(keys) == 2 and all(len(k) == 64 and all(ch in "0123456789abcdef" for ch in k) for k in keys)
    assert not any("pessoa" in k or "203" in k for k in keys)


def test_if_the_database_fails_the_in_memory_limit_still_applies(monkeypatch):
    import app.db as db

    def boom():
        raise RuntimeError("banco fora")

    monkeypatch.setattr(db, "anonymous_session", boom)
    ratelimit.reset()
    got = [ratelimit.check_shared("k:d", 2, now=3_000_000.0) for _ in range(3)]
    assert got[:2] == [None, None] and got[2] is not None                   # nunca abre sem limite


# ---------------------------------------------------------------- login
@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "local_auth", True)
    monkeypatch.setattr(settings, "local_auth_secret", "x" * 40)
    monkeypatch.setattr(settings, "login_per_ip_per_minute", 3)
    monkeypatch.setattr(settings, "login_per_email_per_minute", 1000)
    ratelimit.reset()


def attempt(client, i, xff=None):
    h = {"X-Forwarded-For": xff} if xff else {}
    return client.post("/auth/login", json={"email": f"p{i}@a.example.com", "password": "senha-qualquer-1234"}, headers=h).status_code


def test_login_is_limited_per_source_ip_across_different_emails_and_a_forged_header_does_not_help(client, local):
    codes = [attempt(client, i, xff=f"9.9.9.{i}") for i in range(5)]       # e-mails diferentes e cabeçalho forjado diferente a cada vez
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_login_with_a_trusted_proxy_counts_each_real_client_separately(client, local, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert [attempt(client, i, xff="203.0.113.7") for i in range(4)] == [401, 401, 401, 429]
    assert attempt(client, 9, xff="203.0.113.8") == 401                     # outro cliente real atrás do mesmo proxy: não é bloqueado junto
