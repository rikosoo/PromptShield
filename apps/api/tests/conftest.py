"""Fixtures com Postgres de verdade. Sem DATABASE_URL_TEST (dono/superuser do banco de teste), os testes de banco são pulados."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ADMIN_URL = os.environ.get("DATABASE_URL_TEST")
APP_PW = "app-role-test-password"
API_DIR = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config, items):
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(reason="DATABASE_URL_TEST não definida")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def _alembic(*args: str) -> None:
    env = {**os.environ, "ADMIN_DATABASE_URL": ADMIN_URL, "APP_DB_PASSWORD": APP_PW}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_DIR, env=env, check=True)


@pytest.fixture(scope="session")
def admin_engine():
    if not ADMIN_URL:
        pytest.skip("DATABASE_URL_TEST não definida")
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(ADMIN_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def app_url() -> str:
    return make_url(ADMIN_URL).set(username="promptshield_app", password=APP_PW).render_as_string(hide_password=False)


@pytest.fixture(autouse=True)
def _configure(request):
    """Aponta a aplicação para o papel restrito e limpa os dados entre testes."""
    if "db" not in request.keywords or not ADMIN_URL:
        yield
        return
    from app import db as appdb
    from app.config import settings

    admin_engine = request.getfixturevalue("admin_engine")
    app_url = request.getfixturevalue("app_url")
    settings.database_url = app_url
    settings.oidc_mode = "mock"
    settings.oidc_mock_secret = "x" * 40
    settings.original_text_master_key = base64.urlsafe_b64encode(b"k" * 32).decode()
    appdb.reset_engine()
    from app import crypto

    crypto.clear_cache()
    with admin_engine.begin() as c:
        c.execute(text("TRUNCATE tenants CASCADE"))
    yield
    appdb.reset_engine()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


class World:
    """Dois tenants (A e B) com chave de ingestão e um usuário de cada papel em A."""

    def __init__(self, admin_engine):
        from app.cli import create_tenant
        from app.models import User
        from app.security import issue_mock_token

        self.engine = admin_engine
        with Session(admin_engine) as s, s.begin():
            self.a = create_tenant(s, "Empresa A", "empresa-a", "admin@a.example.com")
            self.b = create_tenant(s, "Empresa B", "empresa-b", "admin@b.example.com")
            tid = uuid.UUID(self.a["tenant_id"])
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            for role in ("analista", "auditor", "leitura"):
                s.add(User(tenant_id=tid, email=f"{role}@a.example.com", role=role, department="Engenharia"))
        self.tok = lambda email: {"Authorization": f"Bearer {issue_mock_token(email)}"}

    def key(self, who="a") -> dict[str, str]:
        return {"X-API-Key": getattr(self, who)["api_key"]}

    def user(self, role: str, tenant="a") -> dict[str, str]:
        return self.tok(f"{role}@a.example.com" if role != "admin" else f"admin@{tenant}.example.com")

    def sql(self, sql: str, **params):
        with self.engine.begin() as c:
            return c.execute(text(sql), params)


@pytest.fixture
def world(admin_engine, _configure):
    return World(admin_engine)


def event(text_value: str = "", kind: str = "prompt", **over):
    base = {
        "event_id": str(uuid.uuid4()),
        # AGORA, não uma data fixa: janelas como "últimos 7 dias" quebram quando o calendário anda (já quebrou duas vezes)
        "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {"channel": "agent_hook", "app": "claude_code", "integration_status": "partial"},
        "actor": {"user_id": "u-42", "department": "Engenharia", "groups": ["devs"]},
        "kind": kind, "content": {"text": text_value}, "context": {"session_id": "s1", "personal_account": False},
    }
    base.update(over)
    return base
