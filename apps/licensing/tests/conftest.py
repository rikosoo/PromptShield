from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
from promptshield_licensing import generate_signing_key
from promptshield_licensing.crypto import private_pem
from sqlalchemy import create_engine, text

APP_DIR = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("DATABASE_URL_TEST")
TABLES = "lic_nonces, lic_authorizations, lic_installations, lic_activation_codes, lic_contracts, lic_customers, lic_audit"


def pytest_collection_modifyitems(config, items):
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(reason="DATABASE_URL_TEST não definida")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def _alembic(*args: str) -> None:
    env = {**os.environ, "LICENSING_ADMIN_DATABASE_URL": ADMIN_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=APP_DIR, env=env, check=True)


@pytest.fixture(scope="session")
def engine():
    if not ADMIN_URL:
        pytest.skip("DATABASE_URL_TEST não definida")
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(ADMIN_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def vendor_key():
    return generate_signing_key()


@pytest.fixture(autouse=True)
def _configure(request):
    if "db" not in request.keywords or not ADMIN_URL:
        yield
        return
    from lic_service import db
    from lic_service.config import settings
    from lic_service.main import reset_limits

    engine = request.getfixturevalue("engine")
    vendor_key = request.getfixturevalue("vendor_key")
    settings.database_url = ADMIN_URL
    settings.license_signing_key = base64.b64encode(private_pem(vendor_key)).decode()
    settings.rate_limit_per_minute = 1000
    db.reset_engine()
    reset_limits()
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield
    db.reset_engine()
