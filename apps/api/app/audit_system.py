"""Auditoria de ações do sistema (worker), sem Principal humano."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def write(session: Session, tenant_id: uuid.UUID, action: str, target_type: str | None = None, target_id: str | None = None,
          detail: dict[str, Any] | None = None, actor_id: str = "worker") -> None:
    session.add(AuditLog(tenant_id=tenant_id, actor_type="system", actor_id=actor_id, action=action, target_type=target_type,
                         target_id=target_id, detail=detail or {}))
