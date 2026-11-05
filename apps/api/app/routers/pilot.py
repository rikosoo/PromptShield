"""Piloto de 30 dias em modo só monitorar: configuração, amostra de revisão (falso positivo) e métricas. Ver docs/piloto.md."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app import audit, pilot
from app.db import tenant_session
from app.models import PilotReview, Tenant
from app.security import Principal, require_roles

router = APIRouter(prefix="/v1/pilot", tags=["piloto"])
READ = ("admin", "analista", "auditor")
REVIEW = ("admin", "analista")


class PilotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_users: int | None = Field(default=None, ge=1, le=1_000_000)
    pilot_days: int | None = Field(default=None, ge=1, le=180)
    start: bool = False   # marca o início do piloto agora


class SampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(default=50, ge=1, le=500)
    min_score: int = Field(default=35, ge=1, le=100)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["verdadeiro_positivo", "falso_positivo", "incerto"]


@router.get("/summary", summary="Cobertura, taxa de falso positivo revisada, tempo até o primeiro alerta")
def get_summary(p: Annotated[Principal, Depends(require_roles(*READ))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        return pilot.summary(s, p.tenant_id)


@router.put("/config", summary="Usuários esperados, duração e início do piloto")
def put_config(body: PilotConfig, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        assert t is not None
        data = body.model_dump(exclude_unset=True)
        if "expected_users" in data:
            t.pilot_expected_users = data["expected_users"]
        if data.get("pilot_days"):
            t.pilot_days = data["pilot_days"]
        if body.start:
            t.pilot_started_at = datetime.now(timezone.utc)
        s.flush()
        audit.write(s, p, "pilot.config", "tenant", str(p.tenant_id), {k: v for k, v in data.items()})
        return pilot.summary(s, p.tenant_id)


@router.post("/samples", status_code=201, summary="Sorteia uma amostra aleatória de eventos sinalizados, ainda não amostrados, para revisão")
def create_sample(body: SampleIn, p: Annotated[Principal, Depends(require_roles(*REVIEW))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        assert t is not None
        since = t.pilot_started_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
        sample_id = uuid.uuid4()
        rows = s.execute(text("""SELECT e.id FROM events e JOIN analyses a ON a.event_pk = e.id
                                 WHERE e.received_at >= :since AND a.risk_score >= :min
                                   AND NOT EXISTS (SELECT 1 FROM pilot_reviews r WHERE r.event_pk = e.id)
                                 ORDER BY random() LIMIT :n"""), {"since": since, "min": body.min_score, "n": body.size}).all()
        for r in rows:
            s.add(PilotReview(tenant_id=p.tenant_id, event_pk=r.id, sample_id=sample_id))
        audit.write(s, p, "pilot.sample", "sample", str(sample_id), {"size": len(rows), "requested": body.size, "min_score": body.min_score})
        return {"sample_id": str(sample_id), "size": len(rows), "requested": body.size, "min_score": body.min_score,
                "note": "amostra aleatória entre os eventos sinalizados ainda não amostrados"}


@router.get("/reviews", summary="Fila de revisão (texto sempre mascarado)")
def list_reviews(p: Annotated[Principal, Depends(require_roles(*REVIEW))], pending_only: bool = True,
                 limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(text(f"""SELECT r.id, r.sample_id, r.label, e.user_id, e.app, e.kind, e.masked_text, a.categories, a.risk_score, a.reasons,
                                  a.decision, a.would_decide, e.occurred_at
                                  FROM pilot_reviews r JOIN events e ON e.id = r.event_pk JOIN analyses a ON a.event_pk = e.id
                                  {"WHERE r.label IS NULL" if pending_only else ""} ORDER BY r.created_at, r.id LIMIT :n"""), {"n": limit}).mappings().all()  # noqa: S608
        return [{"id": str(r["id"]), "sample_id": str(r["sample_id"]), "label": r["label"], "user_id": r["user_id"], "app": r["app"],
                 "kind": r["kind"], "masked_text": r["masked_text"], "categories": r["categories"], "risk_score": r["risk_score"],
                 "reasons": r["reasons"], "decision": r["decision"], "would_decide": r["would_decide"],
                 "occurred_at": r["occurred_at"].isoformat()} for r in rows]


@router.patch("/reviews/{review_id}", summary="Registra o veredito do revisor humano sobre um evento da amostra")
def review(review_id: uuid.UUID, body: ReviewIn, p: Annotated[Principal, Depends(require_roles(*REVIEW))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        r = s.get(PilotReview, review_id)
        if r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "item de revisão não encontrado")
        r.label, r.reviewer_id, r.reviewed_at = body.label, p.id, datetime.now(timezone.utc)
        audit.write(s, p, "pilot.review", "review", str(review_id), {"label": body.label})
        return {"id": str(review_id), "label": body.label}
