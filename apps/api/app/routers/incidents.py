from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import audit
from app.db import tenant_session
from app.models import Analysis, AuditLog, Event, Incident, User
from app.recommendations import recommend
from app.routers.admin import actor_label
from app.schemas import IncidentPatch
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1/incidents", tags=["incidentes"])


def _view(i: Incident, e: Event, a: Analysis, assignee: str | None = None) -> dict:
    confidence = max((c["confidence"] for c in a.categories), default=0.0)
    return {"id": str(i.id), "severity": i.severity, "status": i.status, "assignee_id": str(i.assignee_id) if i.assignee_id else None,
            "assignee_email": assignee, "confidence": confidence,
            "created_at": i.created_at.isoformat(), "event_id": str(e.event_id), "user_id": e.user_id, "app": e.app,
            "department": e.department, "personal_account": e.personal_account,
            "masked_text": e.masked_text, "has_original": e.original_ciphertext is not None, "categories": a.categories,
            "risk_score": a.risk_score, "reasons": a.reasons, "decision": a.decision, "would_decide": a.would_decide}


def _detail(s: Session, incident_id: uuid.UUID) -> dict | None:
    r = s.execute(select(Incident, Event, Analysis, User.email).join(Event, Event.id == Incident.event_pk)
                  .join(Analysis, Analysis.event_pk == Event.id).outerjoin(User, User.id == Incident.assignee_id)
                  .where(Incident.id == incident_id)).first()
    if r is None:
        return None
    i, e, a, assignee = r
    out = _view(i, e, a, assignee)
    steps = [{"at": e.occurred_at.isoformat(), "what": f"Evento capturado em {e.app} (canal {e.channel}, tipo {e.kind})"},
             {"at": a.created_at.isoformat(), "what": f"Analisado: risco {a.risk_score}; decisão {a.decision}"
              + (f" (a política teria decidido {a.would_decide})" if a.would_decide != a.decision else "")},
             {"at": i.created_at.isoformat(), "what": f"Incidente aberto, severidade {i.severity}"}]
    for log in s.execute(select(AuditLog).where(AuditLog.target_type == "incident", AuditLog.target_id == str(incident_id))
                         .order_by(AuditLog.id)).scalars():
        after = (log.detail or {}).get("after", {})
        what = "; ".join(x for x in (f"status: {after['status']}" if "status" in after else "",
                                     "responsável alterado" if "assignee_id" in after else "") if x) or "atualizado"
        steps.append({"at": log.at.isoformat(), "what": f"{what} (por {actor_label(s, log)})"})
    out["timeline"] = sorted(steps, key=lambda x: x["at"])
    out["recommendations"] = recommend(a.categories, a.decision, a.would_decide)
    return out


@router.get("", summary="Fila de incidentes (eventos com risco alto ou crítico)")
def list_incidents(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], status_: str | None = Query(None, alias="status"),
                   severity: str | None = None, assignee_id: uuid.UUID | None = None, category: str | None = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict]:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.sql.expression import cast
    with tenant_session(p.tenant_id) as s:
        q = (select(Incident, Event, Analysis, User.email).join(Event, Event.id == Incident.event_pk)
             .join(Analysis, Analysis.event_pk == Event.id).outerjoin(User, User.id == Incident.assignee_id))
        if status_:
            q = q.where(Incident.status == status_)
        if severity:
            q = q.where(Incident.severity == severity)
        if assignee_id:
            q = q.where(Incident.assignee_id == assignee_id)
        if category:
            q = q.where(cast(Analysis.categories, JSONB).contains([{"id": category}]))
        rows = s.execute(q.order_by(Analysis.risk_score.desc(), Incident.created_at.desc()).limit(limit).offset(offset)).all()
        return [_view(*r) for r in rows]


@router.get("/{incident_id}", summary="Detalhe com linha do tempo e recomendação de resposta")
def get_incident(incident_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        d = _detail(s, incident_id)
        if d is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incidente não encontrado")
        return d


@router.patch("/{incident_id}", summary="Altera status ou responsável")
def patch_incident(incident_id: uuid.UUID, body: IncidentPatch,
                   p: Annotated[Principal, Depends(require_roles("admin", "analista"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        inc = s.get(Incident, incident_id)
        if inc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incidente não encontrado")
        before = {"status": inc.status, "assignee_id": str(inc.assignee_id) if inc.assignee_id else None}
        if body.status:
            inc.status = body.status
        if "assignee_id" in body.model_fields_set:
            if body.assignee_id is not None and s.get(User, body.assignee_id) is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "responsável não existe neste tenant")
            inc.assignee_id = body.assignee_id
        s.execute(text("UPDATE incidents SET updated_at = now() WHERE id = :i"), {"i": incident_id})
        audit.write(s, p, "incident.update", "incident", str(incident_id),
                    {"before": before, "after": body.model_dump(mode="json", exclude_unset=True)})
        s.flush()
        return _detail(s, incident_id)
