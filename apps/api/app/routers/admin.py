from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import audit
from app.db import tenant_session
from app.models import ApiKey, AuditLog, Tenant, User
from app.schemas import ApiKeyIn, ApiKeyRotate, TenantPatch, UserIn
from app.security import Principal, current_principal, generate_api_key, require_ingest, require_roles

router = APIRouter(prefix="/v1", tags=["administração"])


def actor_label(s, log: AuditLog, _cache: dict | None = None) -> str:
    """O registro de auditoria guarda só o UUID do ator; o e-mail vem do cadastro (e some quando o usuário é removido)."""
    if log.actor_type != "user":
        return log.actor_id
    try:
        uid = uuid.UUID(log.actor_id)
    except ValueError:
        return log.actor_id
    email = s.execute(select(User.email).where(User.id == uid)).scalar()
    return email or "(usuário removido)"


@router.get("/me")
def me(p: Annotated[Principal, Depends(current_principal)]) -> dict:
    return {"kind": p.kind, "id": p.id, "tenant_id": str(p.tenant_id), "role": p.role, "email": p.email}


@router.get("/users/directory", summary="Pessoas que podem receber incidentes")
def user_directory(p: Annotated[Principal, Depends(require_roles("admin", "analista"))]) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(User).where(User.active.is_(True)).order_by(User.email)).scalars()
        return [{"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role} for u in rows]


@router.get("/users")
def list_users(p: Annotated[Principal, Depends(require_roles("admin"))]) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        return [{"id": str(u.id), "email": u.email, "role": u.role, "department": u.department, "groups": u.groups, "active": u.active}
                for u in s.execute(select(User).order_by(User.email)).scalars()]


@router.post("/users", status_code=201)
def create_user(body: UserIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        u = User(tenant_id=p.tenant_id, **body.model_dump())
        s.add(u)
        try:
            s.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já cadastrado") from exc
        audit.write(s, p, "user.create", "user", str(u.id), {"role": u.role})  # sem e-mail: o registro é imutável
        return {"id": str(u.id), "email": u.email, "role": u.role}


@router.delete("/users/{user_id}", status_code=204, summary="Remove um usuário do console (o registro de auditoria guarda só o UUID)")
def delete_user(user_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> None:
    with tenant_session(p.tenant_id) as s:
        u = s.get(User, user_id)
        if u is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "usuário não encontrado")
        if str(u.id) == p.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "você não pode remover a si mesmo")
        if u.role == "admin" and s.execute(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True))).scalar_one() <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "não dá para remover o último administrador")
        s.delete(u)
        audit.write(s, p, "user.delete", "user", str(user_id), {"role": u.role})


@router.post("/api-keys", status_code=201, summary="Cria chave de API; o valor completo aparece só nesta resposta")
def create_key(body: ApiKeyIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    key, prefix, digest = generate_api_key()
    with tenant_session(p.tenant_id) as s:
        expires = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
        k = ApiKey(tenant_id=p.tenant_id, name=body.name, prefix=prefix, key_hash=digest, scopes=["ingest"], expires_at=expires)
        s.add(k)
        s.flush()
        audit.write(s, p, "api_key.create", "api_key", str(k.id), {"name": body.name, "prefix": prefix})
        return {"id": str(k.id), "name": k.name, "prefix": prefix, "key": key}


def _key_status(k: ApiKey, now: datetime) -> str:
    if k.revoked_at is not None:
        return "revogada"
    if k.expires_at is not None:
        return "expirada" if k.expires_at <= now else "expira em breve"
    return "ativa"


def _key_view(k: ApiKey, now: datetime) -> dict:
    return {"id": str(k.id), "name": k.name, "prefix": k.prefix, "status": _key_status(k, now), "revoked": k.revoked_at is not None,
            "created_at": k.created_at.isoformat(), "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


@router.get("/api-keys")
def list_keys(p: Annotated[Principal, Depends(require_roles("admin"))]) -> list[dict]:
    now = datetime.now(timezone.utc)
    with tenant_session(p.tenant_id) as s:
        return [_key_view(k, now) for k in s.execute(select(ApiKey).order_by(ApiKey.created_at)).scalars()]


@router.post("/api-keys/{key_id}/revoke")
def revoke_key(key_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        k = s.get(ApiKey, key_id)
        if k is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "chave não encontrada")
        s.execute(text("UPDATE api_keys SET revoked_at = now() WHERE id = :i AND revoked_at IS NULL"), {"i": key_id})
        audit.write(s, p, "api_key.revoke", "api_key", str(key_id), {"prefix": k.prefix})
        return {"id": str(key_id), "revoked": True}


@router.post("/api-keys/{key_id}/rotate", status_code=201,
             summary="Rotaciona: cria uma chave nova (mostrada só aqui) e deixa a antiga valer por `grace_hours` (0 revoga já)")
def rotate_key(key_id: uuid.UUID, body: ApiKeyRotate, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    now = datetime.now(timezone.utc)
    with tenant_session(p.tenant_id) as s:
        old = s.get(ApiKey, key_id)
        if old is None or old.revoked_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "chave não encontrada ou já revogada")
        key, prefix, digest = generate_api_key()
        new = ApiKey(tenant_id=p.tenant_id, name=old.name, prefix=prefix, key_hash=digest, scopes=list(old.scopes))
        s.add(new)
        if body.grace_hours == 0:
            old.revoked_at = now
        else:  # nunca estende uma expiração que já era mais curta
            until = now + timedelta(hours=body.grace_hours)
            old.expires_at = min(until, old.expires_at) if old.expires_at else until
        s.flush()
        audit.write(s, p, "api_key.rotate", "api_key", str(key_id), {"new_prefix": prefix, "old_prefix": old.prefix, "grace_hours": body.grace_hours})
        return {"id": str(new.id), "name": new.name, "prefix": prefix, "key": key, "replaces": str(key_id),
                "old_key_valid_until": None if body.grace_hours == 0 else old.expires_at.isoformat()}


@router.get("/audit-log")
def audit_log(p: Annotated[Principal, Depends(require_roles("admin", "auditor"))], limit: int = 100) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        rows = list(s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).scalars())
        return [{"id": r.id, "at": r.at.isoformat(), "actor": actor_label(s, r), "action": r.action, "target_type": r.target_type,
                 "target_id": r.target_id, "detail": r.detail} for r in rows]



def contract_view(t: Tenant, now: datetime | None = None) -> dict:
    """Situação do contrato para o aviso no console (a decisão de suspender é sempre do fornecedor)."""
    now = now or datetime.now(timezone.utc)
    exp = t.license_expires_at
    return {"suspended": t.suspended_at is not None, "suspended_at": t.suspended_at.isoformat() if t.suspended_at else None,
            "suspended_reason": t.suspended_reason, "license_expires_at": exp.isoformat() if exp else None,
            "days_to_expiry": (exp - now).days if exp else None, "expired": bool(exp and exp <= now)}


def _tenant_view(t: Tenant) -> dict:
    return {"id": str(t.id), "name": t.name, "failure_mode": t.failure_mode, "retention_days": t.retention_days, "original_retention_days": t.original_retention_days, "omit_text_categories": list(t.omit_text_categories),
            "store_original": t.store_original, "policy_url": t.policy_url, "monitored_domains": t.monitored_domains,
            "is_demo": t.is_demo, "volume_threshold_per_hour": t.volume_threshold_per_hour, "contract": contract_view(t)}


@router.get("/tenant", summary="Configurações do tenant")
def get_tenant(p: Annotated[Principal, Depends(require_roles("admin", "analista", "auditor", "leitura"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        return _tenant_view(s.get(Tenant, p.tenant_id))


@router.patch("/tenant", summary="Altera modo de falha, retenção ou guarda do texto original (grava auditoria)")
def patch_tenant(body: TenantPatch, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        before = _tenant_view(t)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(t, k, v)
        s.flush()
        audit.write(s, p, "tenant.update", "tenant", str(p.tenant_id), {"before": before, "after": _tenant_view(t)})
        return _tenant_view(t)


@router.get("/hook-config", summary="Configuração mínima para coletores (modo de falha)")
def hook_config(p: Annotated[Principal, Depends(require_ingest)]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        return {"failure_mode": t.failure_mode}


@router.get("/extension-config", summary="Configuração para a extensão de navegador (domínios, política, modo de falha)")
def extension_config(p: Annotated[Principal, Depends(require_ingest)]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        return {"failure_mode": t.failure_mode, "domains": list(t.monitored_domains), "policy_url": t.policy_url}
