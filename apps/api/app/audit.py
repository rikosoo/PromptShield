from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.security import Principal


def write(session: Session, p: Principal, action: str, target_type: str | None = None,
          target_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    session.add(AuditLog(tenant_id=p.tenant_id, actor_type=p.kind, actor_id=p.id, action=action,
                         target_type=target_type, target_id=target_id, detail=detail or {}))
