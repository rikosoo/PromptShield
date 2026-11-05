"""Usuários e grupos, exceções de política e lista de domínios permitidos. Escrita só do administrador; tudo auditado."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.db import tenant_session
from app.models import AllowlistEntry, Policy, PolicyException, UserGroup, UserGroupMember
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1", tags=["usuários, exceções e listas permitidas"])

MAX_GROUPS, MAX_MEMBERS_PER_CALL, MAX_EXCEPTION_DAYS, MAX_ALLOWLIST = 200, 500, 365, 500
Admin = Annotated[Principal, Depends(require_roles("admin"))]
Reader = Annotated[Principal, Depends(require_roles(*READ_ROLES))]


def _line(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if "\n" in v or "\r" in v or any(ord(c) < 32 for c in v):
        raise ValueError("uma linha só, sem caracteres de controle")
    return v or None


# ---------------------------------------------------------------- grupos

class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    _n = field_validator("name", "description")(_line)

    @field_validator("name")
    @classmethod
    def _need(cls, v: str | None) -> str:
        if not v:
            raise ValueError("nome obrigatório")
        return v


class GroupPatch(BaseModel):
    """O nome não muda: as políticas se referem ao grupo por ele."""
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=300)
    _n = field_validator("description")(_line)


class MembersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=MAX_MEMBERS_PER_CALL)

    @field_validator("user_ids")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out = []
        for x in v:
            x = _line(x)
            if not x:
                raise ValueError("identificador vazio")
            if x not in out:
                out.append(x)
        return out


def _group_view(g: UserGroup, members: int) -> dict:
    return {"id": str(g.id), "name": g.name, "description": g.description, "members": members, "created_at": g.created_at.isoformat()}


def _group(s, group_id: uuid.UUID) -> UserGroup:
    g = s.get(UserGroup, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "grupo não encontrado")
    return g


def _group_refs(s, name: str) -> list[str]:
    """Quem ainda usa o grupo: políticas (escopo) e exceções vigentes."""
    refs = [f"política «{p.name}»" for p in s.execute(select(Policy)).scalars() if name in ((p.scope or {}).get("groups") or [])]
    now = datetime.now(timezone.utc)
    n = s.execute(select(func.count()).select_from(PolicyException).where(
        PolicyException.group_name == name, PolicyException.revoked_at.is_(None), PolicyException.expires_at > now)).scalar_one()
    return refs + ([f"{n} exceção(ões) vigente(s)"] if n else [])


@router.get("/groups", summary="Grupos de usuários e quantos membros cada um tem")
def list_groups(p: Reader) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        counts = dict(s.execute(select(UserGroupMember.group_id, func.count()).group_by(UserGroupMember.group_id)).all())
        return [_group_view(g, counts.get(g.id, 0)) for g in s.execute(select(UserGroup).order_by(UserGroup.name)).scalars()]


@router.post("/groups", status_code=201, summary="Cria um grupo")
def create_group(body: GroupIn, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        if s.execute(select(func.count()).select_from(UserGroup)).scalar_one() >= MAX_GROUPS:
            raise HTTPException(status.HTTP_409_CONFLICT, f"limite de {MAX_GROUPS} grupos")
        if s.execute(select(UserGroup.id).where(func.lower(UserGroup.name) == body.name.lower())).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "já existe um grupo com esse nome")
        g = UserGroup(tenant_id=p.tenant_id, name=body.name, description=body.description)
        s.add(g)
        s.flush()
        audit.write(s, p, "group.create", "group", str(g.id), {"name": g.name})
        s.refresh(g)
        return _group_view(g, 0)


@router.get("/groups/{group_id}", summary="Um grupo com a lista de membros")
def get_group(group_id: uuid.UUID, p: Reader) -> dict:
    with tenant_session(p.tenant_id) as s:
        g = _group(s, group_id)
        members = list(s.execute(select(UserGroupMember.user_id).where(UserGroupMember.group_id == g.id).order_by(UserGroupMember.user_id)).scalars())
        return {**_group_view(g, len(members)), "member_ids": members}


@router.patch("/groups/{group_id}", summary="Altera a descrição (o nome não muda)")
def patch_group(group_id: uuid.UUID, body: GroupPatch, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        g = _group(s, group_id)
        before = g.description
        g.description = body.description
        audit.write(s, p, "group.update", "group", str(g.id), {"name": g.name, "before": before, "after": g.description})
        n = s.execute(select(func.count()).select_from(UserGroupMember).where(UserGroupMember.group_id == g.id)).scalar_one()
        return _group_view(g, n)


@router.delete("/groups/{group_id}", status_code=204, summary="Apaga o grupo, se nenhuma política ou exceção vigente o usa")
def delete_group(group_id: uuid.UUID, p: Admin) -> Response:
    with tenant_session(p.tenant_id) as s:
        g = _group(s, group_id)
        refs = _group_refs(s, g.name)
        if refs:
            raise HTTPException(status.HTTP_409_CONFLICT, "grupo em uso: " + "; ".join(refs))
        audit.write(s, p, "group.delete", "group", str(g.id), {"name": g.name})
        s.delete(g)
    return Response(status_code=204)


@router.post("/groups/{group_id}/members", summary="Adiciona pessoas (pelo identificador que o coletor envia como actor.user_id)")
def add_members(group_id: uuid.UUID, body: MembersIn, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        g = _group(s, group_id)
        have = set(s.execute(select(UserGroupMember.user_id).where(UserGroupMember.group_id == g.id)).scalars())
        new = [u for u in body.user_ids if u not in have]
        for u in new:
            s.add(UserGroupMember(tenant_id=p.tenant_id, group_id=g.id, user_id=u))
        audit.write(s, p, "group.members_add", "group", str(g.id), {"name": g.name, "added": new, "already": len(body.user_ids) - len(new)})
        return {"added": len(new), "already_members": len(body.user_ids) - len(new)}


@router.delete("/groups/{group_id}/members/{user_id}", status_code=204, summary="Tira uma pessoa do grupo")
def remove_member(group_id: uuid.UUID, user_id: str, p: Admin) -> Response:
    with tenant_session(p.tenant_id) as s:
        g = _group(s, group_id)
        n = s.execute(delete(UserGroupMember).where(UserGroupMember.group_id == g.id, UserGroupMember.user_id == user_id)).rowcount
        if not n:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "essa pessoa não está no grupo")
        audit.write(s, p, "group.member_remove", "group", str(g.id), {"name": g.name, "user_id": user_id})
    return Response(status_code=204)


# ---------------------------------------------------------------- exceções

class ExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=200)
    group: str | None = Field(default=None, max_length=60)
    reason: str = Field(min_length=10, max_length=500)
    expires_at: datetime
    _n = field_validator("user_id", "group", "reason")(_line)

    @model_validator(mode="after")
    def _one_target(self) -> ExceptionIn:
        if bool(self.user_id) == bool(self.group):
            raise ValueError("informe uma pessoa OU um grupo")
        if not self.reason or len(self.reason) < 10:
            raise ValueError("o motivo precisa de pelo menos 10 caracteres")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at precisa de fuso horário")
        return self


def _exc_view(x: PolicyException, policy_name: str | None, now: datetime) -> dict:
    state = "revogada" if x.revoked_at else "vencida" if x.expires_at <= now else "vigente"
    return {"id": str(x.id), "policy_id": str(x.policy_id), "policy_name": policy_name, "user_id": x.user_id, "group": x.group_name,
            "reason": x.reason, "expires_at": x.expires_at.isoformat(), "created_by": x.created_by, "created_at": x.created_at.isoformat(),
            "revoked_at": x.revoked_at.isoformat() if x.revoked_at else None, "state": state}


@router.get("/exceptions", summary="Exceções de política (vigentes, vencidas e revogadas)")
def list_exceptions(p: Reader, policy_id: uuid.UUID | None = None, only_active: bool = False) -> list[dict]:
    now = datetime.now(timezone.utc)
    with tenant_session(p.tenant_id) as s:
        q = select(PolicyException, Policy.name).join(Policy, Policy.id == PolicyException.policy_id).order_by(PolicyException.created_at.desc())
        if policy_id:
            q = q.where(PolicyException.policy_id == policy_id)
        if only_active:
            q = q.where(PolicyException.revoked_at.is_(None), PolicyException.expires_at > now)
        return [_exc_view(x, name, now) for x, name in s.execute(q.limit(500)).all()]


@router.post("/policies/{policy_id}/exceptions", status_code=201, summary="Cria exceção: a política deixa de valer para a pessoa ou grupo, até a validade")
def create_exception(policy_id: uuid.UUID, body: ExceptionIn, p: Admin) -> dict:
    now = datetime.now(timezone.utc)
    if body.expires_at <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a validade precisa estar no futuro")
    if body.expires_at > now + timedelta(days=MAX_EXCEPTION_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"a validade máxima é {MAX_EXCEPTION_DAYS} dias (renove depois, com novo motivo)")
    with tenant_session(p.tenant_id) as s:
        pol = s.get(Policy, policy_id)
        if pol is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "política não encontrada")
        if body.group and not s.execute(select(UserGroup.id).where(UserGroup.name == body.group)).first():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "grupo não existe (exceção por grupo usa só grupos cadastrados)")
        x = PolicyException(tenant_id=p.tenant_id, policy_id=policy_id, user_id=body.user_id, group_name=body.group,
                            reason=body.reason, expires_at=body.expires_at, created_by=p.id)
        s.add(x)
        s.flush()
        audit.write(s, p, "exception.create", "policy", str(policy_id), {"exception_id": str(x.id), "policy": pol.name, "user_id": x.user_id,
                                                                          "group": x.group_name, "reason": x.reason, "expires_at": x.expires_at.isoformat()})
        s.refresh(x)
        return _exc_view(x, pol.name, now)


@router.post("/exceptions/{exception_id}/revoke", summary="Revoga a exceção (vale já para os próximos eventos)")
def revoke_exception(exception_id: uuid.UUID, p: Admin) -> dict:
    now = datetime.now(timezone.utc)
    with tenant_session(p.tenant_id) as s:
        x = s.get(PolicyException, exception_id)
        if x is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "exceção não encontrada")
        if x.revoked_at is None:
            x.revoked_at, x.revoked_by = now, p.id
            audit.write(s, p, "exception.revoke", "policy", str(x.policy_id), {"exception_id": str(x.id), "user_id": x.user_id, "group": x.group_name})
        pol = s.get(Policy, x.policy_id)
        return _exc_view(x, pol.name if pol else None, now)


# ---------------------------------------------------------------- lista de domínios permitidos

HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BROAD = {"com", "net", "org", "io", "br", "com.br", "co", "dev", "app", "cloud", "online", "xyz"}


class AllowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = "host"
    value: str = Field(min_length=3, max_length=253)
    note: str | None = Field(default=None, max_length=300)
    _n = field_validator("note")(_line)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v != "host":
            raise ValueError("por enquanto só 'host' (domínio)")
        return v

    @field_validator("value")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        if "://" in v or "/" in v or ":" in v or "@" in v or "*" in v:
            raise ValueError("informe só o domínio, sem http://, caminho, porta ou curinga (ex.: api.empresa.com.br)")
        if not HOST_RE.match(v):
            raise ValueError("domínio inválido")
        if v in BROAD:
            raise ValueError("domínio amplo demais: informe o domínio da sua empresa ou do serviço")
        return v


def _allow_view(a: AllowlistEntry) -> dict:
    return {"id": str(a.id), "kind": a.kind, "value": a.value, "note": a.note, "created_by": a.created_by, "created_at": a.created_at.isoformat()}


@router.get("/allowlist", summary="Domínios permitidos: destino aprovado, não gera alerta de rede externa nem de envio de dados")
def list_allowlist(p: Reader) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        return [_allow_view(a) for a in s.execute(select(AllowlistEntry).order_by(AllowlistEntry.value)).scalars()]


@router.post("/allowlist", status_code=201, summary="Permite um domínio (vale para os próximos eventos; subdomínios incluídos)")
def add_allowlist(body: AllowIn, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        if s.execute(select(func.count()).select_from(AllowlistEntry)).scalar_one() >= MAX_ALLOWLIST:
            raise HTTPException(status.HTTP_409_CONFLICT, f"limite de {MAX_ALLOWLIST} entradas")
        a = AllowlistEntry(tenant_id=p.tenant_id, kind=body.kind, value=body.value, note=body.note, created_by=p.id)
        s.add(a)
        try:
            s.flush()
        except IntegrityError:
            raise HTTPException(status.HTTP_409_CONFLICT, "esse domínio já está na lista") from None
        audit.write(s, p, "allowlist.add", "allowlist", str(a.id), {"kind": a.kind, "value": a.value, "note": a.note})
        s.refresh(a)
        return _allow_view(a)


@router.delete("/allowlist/{entry_id}", status_code=204, summary="Tira o domínio da lista")
def remove_allowlist(entry_id: uuid.UUID, p: Admin) -> Response:
    with tenant_session(p.tenant_id) as s:
        a = s.get(AllowlistEntry, entry_id)
        if a is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "entrada não encontrada")
        audit.write(s, p, "allowlist.remove", "allowlist", str(a.id), {"kind": a.kind, "value": a.value})
        s.delete(a)
    return Response(status_code=204)
