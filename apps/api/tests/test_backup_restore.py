"""Etapa 9, operação: backup e restauração TESTADOS de ponta a ponta contra o PostgreSQL local.

Prova: os dados voltam, a RLS e a imutabilidade da auditoria continuam valendo, o papel restrito só vê o próprio tenant, e a chave
mestra NÃO está no backup (sem ela o texto original não abre; com ela abre)."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import ADMIN_URL, APP_PW, event
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import crypto
from app.config import settings

pytestmark = [pytest.mark.db, pytest.mark.skipif(not (shutil.which("pg_dump") and shutil.which("pg_restore") and shutil.which("psql")),
                                                  reason="pg_dump/pg_restore/psql não instalados")]
ROOT = Path(__file__).resolve().parents[3]
SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def libpq(url: str, database: str | None = None) -> str:
    u = make_url(url)
    if database:
        u = u.set(database=database)
    return u.set(drivername="postgresql").render_as_string(hide_password=False)


def test_backup_and_restore_round_trip(client, world, admin_engine, tmp_path):
    assert client.patch("/v1/tenant", json={"store_original": True}, headers=world.user("admin")).status_code == 200
    ev = event(f"deploy com {SECRET}")
    assert client.post("/v1/events", json=ev, headers=world.key()).status_code == 200
    assert client.post("/v1/events", json=event("outro"), headers=world.key("b")).status_code == 200
    expected = {t: world.sql(f"SELECT count(*) FROM {t}").scalar() for t in  # noqa: S608 - nomes fixos do teste
                ("tenants", "users", "api_keys", "policies", "events", "analyses", "incidents", "alerts", "audit_log", "tenant_keys")}
    assert expected["events"] == 2 and expected["tenant_keys"] == 1

    dump = tmp_path / "bk.dump"
    env = {**os.environ, "PGPASSWORD": make_url(ADMIN_URL).password or ""}
    subprocess.run([str(ROOT / "infra/backup.sh"), libpq(ADMIN_URL), str(dump)], check=True, env=env, capture_output=True)
    assert dump.stat().st_size > 1000 and (tmp_path / "bk.dump.sha256").exists()

    # a chave mestra e o texto do prompt não aparecem em claro no arquivo de backup
    raw = dump.read_bytes()
    assert settings.original_text_master_key.encode() not in raw and SECRET.encode() not in raw

    name = f"ps_restore_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        restored = libpq(ADMIN_URL, name)
        # recusa restaurar sobre banco que não está vazio
        busy = subprocess.run([str(ROOT / "infra/restore.sh"), str(dump), libpq(ADMIN_URL)], env=env, capture_output=True, text=True)
        assert busy.returncode == 2 and "não está vazio" in busy.stderr
        # soma adulterada é recusada
        bad = tmp_path / "bad.dump"
        bad.write_bytes(raw + b"x")
        shutil.copy(tmp_path / "bk.dump.sha256", tmp_path / "bad.dump.sha256")
        (tmp_path / "bad.dump.sha256").write_text((tmp_path / "bk.dump.sha256").read_text().replace("bk.dump", "bad.dump"))
        assert subprocess.run([str(ROOT / "infra/restore.sh"), str(bad), restored], env=env, capture_output=True).returncode != 0
        subprocess.run([str(ROOT / "infra/restore.sh"), str(dump), restored], check=True, env=env, capture_output=True)

        eng = create_engine(make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False))  # não usar replace: o nome do banco pode coincidir com usuário/senha
        with eng.begin() as c:
            got = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in expected}  # noqa: S608
            assert got == expected                                                       # tudo voltou
            flags = c.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN "
                                   "('events','analyses','incidents','audit_log','tenant_keys','alerts','inference_hook_configs')")).all()
            assert len(flags) == 7 and all(f.relrowsecurity and f.relforcerowsecurity for f in flags)
            assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname IN ('auth_api_key','auth_user_by_email','list_tenant_ids')")).scalar() == 3
            with pytest.raises(Exception, match="imut"):                                   # o gatilho da auditoria também voltou
                c.execute(text("DELETE FROM audit_log"))
        with eng.begin() as c:
            wrapped = c.execute(text("SELECT data_key_wrapped FROM tenant_keys WHERE tenant_id = :t"), {"t": world.a["tenant_id"]}).scalar()
            blob = bytes(c.execute(text("SELECT original_ciphertext FROM events WHERE event_id = :e"), {"e": ev["event_id"]}).scalar())

        # o papel restrito da aplicação, no banco restaurado, só vê o próprio tenant
        app_eng = create_engine(make_url(ADMIN_URL).set(database=name, username="promptshield_app", password=APP_PW)
                                .render_as_string(hide_password=False))
        with app_eng.begin() as c:
            assert c.execute(text("SELECT count(*) FROM events")).scalar() == 0           # sem tenant definido: nada
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": world.a["tenant_id"]})
            assert c.execute(text("SELECT count(*) FROM events")).scalar() == 1
        app_eng.dispose()
        eng.dispose()

        # com a chave mestra certa o texto original abre; com outra, não
        dek = crypto._wrapper(crypto._master()).decrypt(bytes(wrapped))
        key = base64.urlsafe_b64encode(crypto._hkdf(dek, b"promptshield/original"))
        assert SECRET in Fernet(key).decrypt(blob[len(crypto.PREFIX):]).decode()
        other = base64.urlsafe_b64encode(b"m" * 32).decode()
        with pytest.raises(InvalidToken):
            crypto._wrapper(crypto._master(other)).decrypt(bytes(wrapped))
    finally:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_restore_survives_a_newer_pg_restore_client(client, world, admin_engine, tmp_path):
    """Regressão do CI de 2026-10-20: pg_restore mais novo que o servidor escreve `SET transaction_timeout`, que o servidor 16 recusa."""
    assert client.post("/v1/events", json=event("simulado"), headers=world.key()).status_code == 200
    env = {**os.environ, "PGPASSWORD": make_url(ADMIN_URL).password or ""}
    dump = tmp_path / "bk.dump"
    subprocess.run([str(ROOT / "infra/backup.sh"), libpq(ADMIN_URL), str(dump)], check=True, env=env, capture_output=True)
    shim = tmp_path / "bin" / "pg_restore"
    shim.parent.mkdir()
    # imita um pg_restore 17+ contra servidor 16: ligado direto ao banco (--dbname) ele falha em `SET transaction_timeout`; como gerador de SQL só escreve a linha
    shim.write_text('#!/bin/sh\ncase "$*" in *--dbname*) echo "ERROR: unrecognized configuration parameter transaction_timeout" >&2; exit 1;; esac\n'
                    '[ "$2" = "-f" ] && echo "SET transaction_timeout = 0;"\nexec "$REAL_PG_RESTORE" "$@"\n')
    shim.chmod(0o755)
    name = f"ps_restore_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        shimmed = {**env, "REAL_PG_RESTORE": shutil.which("pg_restore") or "", "PATH": f"{shim.parent}:{env['PATH']}"}
        done = subprocess.run([str(ROOT / "infra/restore.sh"), str(dump), libpq(ADMIN_URL, name)], env=shimmed, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        eng = create_engine(make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False))
        with eng.begin() as c:
            assert c.execute(text("SELECT count(*) FROM events")).scalar() == 1
        eng.dispose()
    finally:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
