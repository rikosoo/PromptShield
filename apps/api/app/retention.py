"""Retenção por tenant: apaga o que venceu. Usa `received_at` (hora do servidor), não `occurred_at` (vem do coletor).

- `original_retention_days` (padrão 30, no máximo `retention_days`): só o texto ORIGINAL cifrado é apagado (o mascarado fica).
- `retention_days` (padrão 90): apaga eventos (e, em cascata, análises e incidentes), alertas, fila de envio concluída,
  registros de requisições dos inference hooks e relatórios gerados.
- O registro de auditoria (`audit_log`) é imutável e NÃO é apagado aqui: ele não traz texto de prompt, só UUIDs e justificativas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit_system
from app.models import Tenant


def run(session: Session, tenant_id: uuid.UUID, now: datetime | None = None, actor: str = "retention") -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    t = session.get(Tenant, tenant_id)
    assert t is not None
    cutoff = now - timedelta(days=t.retention_days)
    original_cutoff = now - timedelta(days=min(t.original_retention_days, t.retention_days))
    c = {"p": cutoff, "o": original_cutoff}
    counts = {
        "originals_erased": session.execute(text("UPDATE events SET original_ciphertext = NULL "
                                                 "WHERE original_ciphertext IS NOT NULL AND received_at < :o"), c).rowcount,
        "events": session.execute(text("DELETE FROM events WHERE received_at < :p"), c).rowcount,  # cascata: análises e incidentes
        "alerts": session.execute(text("DELETE FROM alerts WHERE last_seen < :p"), c).rowcount,
        "outbox": session.execute(text("DELETE FROM notification_outbox WHERE created_at < :p AND status <> 'pending'"), c).rowcount,
        "hook_requests": session.execute(text("DELETE FROM inference_hook_requests WHERE created_at < :p"), c).rowcount,
        "reports": session.execute(text("DELETE FROM reports WHERE created_at < :p"), c).rowcount,
    }
    t.last_retention_run = now
    audit_system.write(session, tenant_id, "retention.run", "tenant", str(tenant_id),
                       {**counts, "retention_days": t.retention_days, "original_retention_days": t.original_retention_days, "actor": actor})
    return counts


def due(session: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    t = session.get(Tenant, tenant_id)
    return t is not None and (t.last_retention_run is None or t.last_retention_run < now - timedelta(hours=23))
