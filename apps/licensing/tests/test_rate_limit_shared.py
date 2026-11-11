"""Limite compartilhado entre processos e IP de origem atrás de proxy, no serviço do fornecedor. Dados SINTÉTICOS."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from lic_service import ratelimit
from lic_service.clientip import client_ip


def req(peer="10.0.0.9", xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_forwarded_header_is_ignored_by_default_and_the_nth_from_the_right_counts_when_configured():
    assert client_ip(req(xff="1.2.3.4"), hops=0) == "10.0.0.9"
    assert client_ip(req(xff="6.6.6.6, 203.0.113.7"), hops=1) == "203.0.113.7"          # o 6.6.6.6 foi forjado pelo cliente: ignorado
    assert client_ip(req(xff="lixo"), hops=1) == "10.0.0.9"
    assert client_ip(req(xff="203.0.113.7"), hops=2) == "10.0.0.9"


@pytest.mark.db
def test_the_limit_is_shared_across_processes_and_stores_only_a_hash(engine):
    from sqlalchemy import text

    got = []
    for _ in range(4):
        ratelimit.reset()                                                       # simula OUTRO processo (memória vazia)
        got.append(ratelimit.count("api:203.0.113.7"))
    assert got == [1, 2, 3, 4]                                                  # o contador continua, porque está no banco
    with engine.begin() as c:
        keys = [r[0] for r in c.execute(text("SELECT key FROM lic_rate_hits")).all()]
    assert len(keys) == 1 and len(keys[0]) == 64 and "203" not in keys[0]


@pytest.mark.db
def test_http_endpoints_are_limited_per_real_ip_and_a_forged_header_does_not_help(monkeypatch):
    from fastapi.testclient import TestClient

    from lic_service.config import settings
    from lic_service.main import app

    client = TestClient(app)

    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    ratelimit.reset()
    body = {"request": "pr1." + "x" * 40}                  # inválido, mas passa pela validação de formato: o limite vem antes de olhar a assinatura
    codes = [client.post("/v1/renew", json=body, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(5)]
    assert codes[3:] == [429, 429] and 429 not in codes[:3]


def test_if_the_database_fails_the_process_memory_still_limits(monkeypatch):
    import lic_service.db as db

    def boom():
        raise RuntimeError("banco fora")

    monkeypatch.setattr(db, "session_scope", boom)
    ratelimit.reset()
    assert [ratelimit.count("k:x") for _ in range(3)] == [1, 2, 3]
