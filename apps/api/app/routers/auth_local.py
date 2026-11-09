"""Login do console com e-mail e senha (opcional: LOCAL_AUTH=true) e troca da própria senha.

Segurança: a senha só existe como hash (scrypt); a resposta de falha é a mesma para e-mail inexistente, senha errada, conta sem senha e conta bloqueada
(não revela quem existe); cada tentativa gasta o mesmo tempo; erros seguidos bloqueiam o acesso por alguns minutos; trocar a senha derruba as sessões abertas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app import audit, metrics, passwords, ratelimit
from app.config import settings
from app.db import anonymous_session, tenant_session
from app.models import User
from app.security import ROLES, Principal, issue_local_token, require_roles

router = APIRouter(tags=["login com senha"])
GENERIC = "e-mail ou senha incorretos, ou acesso bloqueado por tentativas seguidas (tente de novo em alguns minutos)"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)      # sem política aqui: quem confere é o hash


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _enabled() -> None:
    if not (settings.local_auth and settings.local_auth_secret):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "login com senha desligado neste servidor")


def _token_body(user_id: str, email: str, version: int, must_change: bool) -> dict:
    token, ttl = issue_local_token(user_id, email, version)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "must_change_password": must_change}


def _count(user_id: uuid.UUID, ok: bool) -> None:
    """Registra o resultado em transação própria (precisa valer mesmo quando a requisição termina em erro)."""
    with anonymous_session() as s:
        s.execute(text("SELECT auth_login_result(:u, :ok, :m, :l)"), {"u": user_id, "ok": ok, "m": settings.login_max_failures, "l": settings.login_lock_minutes})


@router.post("/auth/login", summary="Entra com e-mail e senha (LOCAL_AUTH=true); devolve uma sessão assinada")
def login(body: LoginIn) -> dict:
    _enabled()
    email = body.email.strip().lower()
    for key, limit in (("login:all", settings.login_global_per_minute), (f"login:{email}", settings.login_per_email_per_minute)):
        wait = ratelimit.check(key, limit)
        if wait is not None:
            metrics.inc("ps_login_total", result="rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "muitas tentativas; aguarde um pouco", headers={"Retry-After": str(wait)})
    with anonymous_session() as s:
        row = s.execute(text("SELECT user_id, tenant_id, password_hash, password_version, must_change_password, locked_until FROM auth_login_lookup(:e)"), {"e": email}).first()
    locked = row is not None and row.locked_until is not None and row.locked_until > datetime.now(timezone.utc)
    ok = passwords.verify_password(body.password, row.password_hash if row is not None and not locked else None)    # None: gasta o mesmo tempo
    if row is not None and not locked:
        _count(row.user_id, ok)
    if row is None or locked or not ok:
        metrics.inc("ps_login_total", result="locked" if locked else "fail")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC, headers={"WWW-Authenticate": "Bearer"})
    metrics.inc("ps_login_total", result="ok")
    return _token_body(str(row.user_id), email, row.password_version, bool(row.must_change_password))


@router.post("/v1/me/password", summary="Troca a própria senha (também com senha provisória); devolve uma sessão nova, as antigas deixam de valer")
def change_my_password(body: PasswordChangeIn, p: Annotated[Principal, Depends(require_roles(*ROLES))]) -> dict:
    _enabled()
    if (msg := passwords.policy_message(body.new_password)) is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)
    with tenant_session(p.tenant_id) as s:
        u = s.get(User, uuid.UUID(p.id))
        if u is None or not u.password_hash:
            raise HTTPException(status.HTTP_409_CONFLICT, "este usuário não tem senha local (ele entra pelo login da empresa)")
        stored, locked_until = u.password_hash, u.locked_until
    if locked_until is not None and locked_until > datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "muitas tentativas erradas; aguarde alguns minutos")
    if not passwords.verify_password(body.current_password, stored):
        _count(uuid.UUID(p.id), False)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a senha atual está incorreta")
    if passwords.verify_password(body.new_password, stored):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a nova senha precisa ser diferente da atual")
    new_hash = passwords.hash_password(body.new_password)
    with tenant_session(p.tenant_id) as s:
        u = s.get(User, uuid.UUID(p.id))
        assert u is not None
        u.password_hash, u.password_version, u.must_change_password = new_hash, u.password_version + 1, False
        u.failed_logins, u.locked_until, u.password_changed_at = 0, None, datetime.now(timezone.utc)
        audit.write(s, p, "user.password_change", "user", str(u.id), {})       # nunca a senha nem o hash
        version = u.password_version
    metrics.inc("ps_password_changes_total")
    return _token_body(p.id, p.email or "", version, False)
