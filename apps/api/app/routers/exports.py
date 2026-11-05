"""Exportação para SIEM por consulta (pull): CEF em texto e JSON Lines. Mascarado, sem o texto do prompt."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app import audit, cef
from app.config import settings
from app.db import tenant_session
from app.models import Analysis, Event
from app.security import Principal, require_roles
from app.siem import event_record, json_safe

router = APIRouter(prefix="/v1/export", tags=["exportação SIEM"])
ROLES = ("admin", "auditor")


def _rows(p: Principal, since: datetime | None, min_score: int, limit: int, fmt: str):
    since = since or datetime.now(timezone.utc) - timedelta(days=1)
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id)
                         .where(Event.occurred_at >= since, Analysis.risk_score >= min_score)
                         .order_by(Event.occurred_at, Event.id).limit(limit)).all()
        recs = [event_record(e, a) for e, a in rows]
        audit.write(s, p, "export.siem", "events", None, {"format": fmt, "since": since.isoformat(), "min_score": min_score, "rows": len(recs)})
    return recs


@router.get("/cef", response_class=PlainTextResponse, summary="Eventos em CEF (uma linha por evento)")
def export_cef(p: Annotated[Principal, Depends(require_roles(*ROLES))], since: datetime | None = None,
               min_score: int = Query(35, ge=0, le=100), limit: int = Query(1000, ge=1, le=10000)) -> str:
    return "".join(cef.event_to_cef(r, settings.version) + "\n" for r in _rows(p, since, min_score, limit, "cef"))


@router.get("/events.jsonl", response_class=PlainTextResponse, summary="Eventos em JSON Lines")
def export_jsonl(p: Annotated[Principal, Depends(require_roles(*ROLES))], since: datetime | None = None,
                 min_score: int = Query(35, ge=0, le=100), limit: int = Query(1000, ge=1, le=10000)) -> str:
    return "".join(json.dumps(json_safe(r), sort_keys=True, ensure_ascii=False) + "\n" for r in _rows(p, since, min_score, limit, "jsonl"))
