"""Autenticação: chaves de API dos coletores (só o hash é guardado) e tokens OIDC do console."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import text

from app import license_client, metrics, ratelimit
from app.config import settings
from app.db import anonymous_session

ROLES = ("admin", "analista", "auditor", "leitura")
KEY_PREFIX = "ps_"


@dataclass(frozen=True)
class Principal:
    kind: str                       # "api_key" | "user"
    id: str
    tenant_id: uuid.UUID
    role: str | None = None         # só para usuários
    scopes: tuple[str, ...] = ()    # só para chaves
    department: str | None = None
    email: str | None = None


def hash_key(key: str) -> str:
    # chaves têm 192 bits de entropia: SHA-256 simples basta (não é senha de humano)
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Devolve (chave completa, prefixo visível, hash). A chave completa é mostrada uma única vez."""
    prefix = secrets.token_hex(4)
    key = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(24)}"
    return key, f"{KEY_PREFIX}{prefix}", hash_key(key)


def _unauthorized(detail: str = "credenciais inválidas") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


# ---------- OIDC ----------
class KeyProvider:
    """Ponto de extensão (e de teste) para obter a chave de verificação do token."""

    def key_for(self, token: str) -> tuple[Any, list[str]]:  # pragma: no cover - interface
        raise NotImplementedError


class JwksKeyProvider(KeyProvider):
    def __init__(self, jwks_url: str) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True)

    def key_for(self, token: str) -> tuple[Any, list[str]]:
        return self._client.get_signing_key_from_jwt(token).key, ["RS256", "ES256"]


_provider: KeyProvider | None = None


def set_key_provider(p: KeyProvider | None) -> None:
    global _provider
    _provider = p


def verify_token(token: str) -> dict[str, Any]:
    mode = settings.oidc_mode
    try:
        if mode == "mock":
            if not settings.oidc_mock_secret:
                raise _unauthorized("OIDC mock sem segredo configurado")
            return jwt.decode(token, settings.oidc_mock_secret, algorithms=["HS256"], issuer="promptshield-mock",
                              audience="promptshield-console", options={"require": ["exp", "iss", "aud", "sub"]})
        if mode == "oidc":
            global _provider
            if _provider is None:
                if not settings.oidc_jwks_url:
                    raise _unauthorized("OIDC sem jwks_url configurado")
                _provider = JwksKeyProvider(settings.oidc_jwks_url)
            key, algs = _provider.key_for(token)
            return jwt.decode(token, key, algorithms=algs, issuer=settings.oidc_issuer, audience=settings.oidc_audience,
                              options={"require": ["exp", "iss", "aud", "sub"]})
    except jwt.PyJWTError as exc:
        raise _unauthorized("token inválido ou expirado") from exc
    raise _unauthorized("login do console desligado (OIDC_MODE=off)")


def issue_mock_token(email: str, ttl_seconds: int = 3600) -> str:
    import time

    now = int(time.time())
    return jwt.encode({"iss": "promptshield-mock", "aud": "promptshield-console", "sub": email, "email": email,
                       "email_verified": True, "iat": now, "exp": now + ttl_seconds},
                      settings.oidc_mock_secret or "", algorithm="HS256")


# ---------- dependências FastAPI ----------
def _resolve_key(raw: str) -> Principal:
    with anonymous_session() as s:
        row = s.execute(text("SELECT key_id, tenant_id, scopes FROM auth_api_key(:h)"), {"h": hash_key(raw)}).first()
    if row is None:
        raise _unauthorized()
    return Principal(kind="api_key", id=str(row.key_id), tenant_id=row.tenant_id, scopes=tuple(row.scopes))


def _resolve_user(token: str) -> Principal:
    claims = verify_token(token)
    email = claims.get("email")
    if not email or claims.get("email_verified") is not True:
        raise _unauthorized("o token precisa trazer e-mail verificado")
    with anonymous_session() as s:
        row = s.execute(text("SELECT user_id, tenant_id, role, department FROM auth_user_by_email(:e)"), {"e": email}).first()
    if row is None:
        raise _unauthorized("usuário não cadastrado ou inativo")
    return Principal(kind="user", id=str(row.user_id), tenant_id=row.tenant_id, role=row.role,
                     department=row.department, email=email)


SUSPENDED_DETAIL = "contrato suspenso: a coleta e as alterações estão paradas; os dados continuam guardados. Fale com o fornecedor."
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def tenant_suspension(tenant_id: uuid.UUID) -> tuple[Any, str | None] | None:
    """(desde quando, motivo) se a empresa está suspensa; None se não. Uma consulta pequena por requisição (sem cache: a suspensão vale na hora)."""
    with anonymous_session() as s:
        row = s.execute(text("SELECT suspended_at, reason FROM tenant_suspension(:t)"), {"t": tenant_id}).first()
    return (row.suspended_at, row.reason) if row else None


def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    raw = x_api_key or _bearer(authorization)
    if not raw:
        raise _unauthorized("envie X-API-Key ou Authorization: Bearer")
    p = _resolve_key(raw) if raw.startswith(KEY_PREFIX) else _resolve_user(raw)
    request.state.tenant_id = str(p.tenant_id)  # para o log de acesso
    if tenant_suspension(p.tenant_id) is not None:
        # coletores: tudo recusado (o sensor segue em fail_mode open: os funcionários continuam trabalhando, só o monitoramento para).
        # console: o administrador ainda entra e LÊ (e exporta) os dados, mas nada é alterado.
        if p.kind == "api_key" or request.method not in SAFE_METHODS:
            metrics.inc("ps_suspended_refusals_total", kind=p.kind)
            raise HTTPException(status.HTTP_403_FORBIDDEN, SUSPENDED_DETAIL, headers={"X-PromptShield-Suspended": "1"})
    limit = settings.rate_limit_key_per_minute if p.kind == "api_key" else settings.rate_limit_user_per_minute
    wait = ratelimit.check(f"{p.kind}:{p.id}", limit)
    if wait is not None:
        metrics.inc("ps_rate_limited_total", kind=p.kind)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "limite de requisições excedido", headers={"Retry-After": str(wait)})
    if settings.license_mode == "onprem":
        ls = license_client.state()
        if not ls.inspecting:
            # a inspeção está parada pela licença: aparece nos sensores (cabeçalho) e no console; ninguém perde dados nem acesso de leitura
            if p.kind == "api_key":
                metrics.inc("ps_license_refusals_total", kind="api_key")
                raise HTTPException(status.HTTP_403_FORBIDDEN, ls.message, headers={"X-PromptShield-Inspection": "stopped"})
            if request.method not in SAFE_METHODS and not request.url.path.startswith("/v1/license/"):
                metrics.inc("ps_license_refusals_total", kind="user")
                raise HTTPException(status.HTTP_403_FORBIDDEN, ls.message, headers={"X-PromptShield-Inspection": "stopped"})
    return p


def require_ingest(p: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if p.kind != "api_key" or "ingest" not in p.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "esta rota exige uma chave de API com escopo ingest")
    return p


def require_roles(*roles: str):
    def dep(p: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if p.kind != "user" or p.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"exige papel: {', '.join(roles)}")
        return p

    return dep


READ_ROLES = ("admin", "analista", "auditor", "leitura")
