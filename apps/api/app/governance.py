"""Contexto de governança do tenant lido na ingestão: grupos do usuário, exceções vigentes e domínios permitidos.

Tudo roda na sessão do tenant (RLS). Funções simples, sem regra de negócio escondida: a regra de exceção está em `policy_engine`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AllowlistEntry, PolicyException, UserGroup, UserGroupMember


def member_groups(session: Session, user_id: str) -> tuple[str, ...]:
    rows = session.execute(select(UserGroup.name).join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
                           .where(UserGroupMember.user_id == user_id).order_by(UserGroup.name)).scalars()
    return tuple(rows)


def groups_of_users(session: Session, user_ids: set[str]) -> dict[str, tuple[str, ...]]:
    """Para a simulação: grupos de várias pessoas de uma vez."""
    out: dict[str, list[str]] = {}
    if not user_ids:
        return {}
    rows = session.execute(select(UserGroupMember.user_id, UserGroup.name).join(UserGroup, UserGroup.id == UserGroupMember.group_id)
                           .where(UserGroupMember.user_id.in_(user_ids))).all()
    for uid, name in rows:
        out.setdefault(uid, []).append(name)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def active_exceptions(session: Session, now: datetime | None = None) -> dict[str, tuple[dict, ...]]:
    """Exceções não revogadas e não vencidas, por id da política."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, list[dict]] = {}
    for x in session.execute(select(PolicyException).where(PolicyException.revoked_at.is_(None), PolicyException.expires_at > now)).scalars():
        out.setdefault(str(x.policy_id), []).append({"user_id": x.user_id, "group": x.group_name, "expires_at": x.expires_at})
    return {k: tuple(v) for k, v in out.items()}


def allowed_hosts(session: Session) -> tuple[str, ...]:
    return tuple(session.execute(select(AllowlistEntry.value).where(AllowlistEntry.kind == "host").order_by(AllowlistEntry.value)).scalars())
