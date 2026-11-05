"""Direitos do titular (LGPD art. 18, GDPR arts. 15 e 17) sobre os dados das PESSOAS MONITORADAS, e retenção sob demanda.

O pedido é feito pelo controlador (a empresa cliente) ao administrador; esta API é a ferramenta, não o canal de atendimento.
O registro de auditoria guarda só o hash do identificador, a justificativa e as contagens (nunca o identificador em claro).
"""
from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app import audit, retention
from app.db import tenant_session
from app.models import Analysis, Event
from app.security import Principal, require_roles

router = APIRouter(prefix="/v1/privacy", tags=["privacidade"])
MAX_EXPORT = 5000


class EraseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=200)
    justification: str = Field(min_length=10, max_length=1000)


def subject_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.strip().lower().encode()).hexdigest()


@router.get("/subject", summary="Acesso do titular: tudo o que o produto guarda sobre uma pessoa monitorada (texto sempre mascarado)")
def subject_export(p: Annotated[Principal, Depends(require_roles("admin", "auditor"))],
                   user_id: str = Query(min_length=1, max_length=200)) -> dict:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id)
                         .where(Event.user_id == user_id).order_by(Event.occurred_at).limit(MAX_EXPORT + 1)).all()
        truncated = len(rows) > MAX_EXPORT
        rows = rows[:MAX_EXPORT]
        incidents = s.execute(text("SELECT count(*) FROM incidents i JOIN events e ON e.id = i.event_pk WHERE e.user_id = :u"), {"u": user_id}).scalar_one()
        alerts = s.execute(text("SELECT count(*) FROM alerts WHERE user_id = :u"), {"u": user_id}).scalar_one()
        audit.write(s, p, "privacy.subject_export", "subject", subject_hash(user_id), {"events": len(rows), "truncated": truncated})
        return {"subject": user_id, "events": [
            {"event_id": str(e.event_id), "occurred_at": e.occurred_at.isoformat(), "app": e.app, "channel": e.channel, "kind": e.kind,
             "personal_account": e.personal_account, "masked_text": e.masked_text, "has_original": e.original_ciphertext is not None,
             "categories": a.categories, "risk_score": a.risk_score, "decision": a.decision} for e, a in rows],
            "incidents": incidents, "alerts": alerts, "truncated": truncated,
            "note": "O texto original cifrado nunca sai por esta rota. Relatórios já gerados não são pesquisados: veja GET /v1/reports."}


@router.post("/subject/erase", summary="Eliminação a pedido do titular: apaga eventos, análises, incidentes e alertas de uma pessoa")
def subject_erase(body: EraseIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        ids = [r.id for r in s.execute(text("SELECT id FROM events WHERE user_id = :u"), {"u": body.user_id})]
        alert_ids = [r.id for r in s.execute(text("SELECT id FROM alerts WHERE user_id = :u"), {"u": body.user_id})]
        incidents = s.execute(text("SELECT count(*) FROM incidents i JOIN events e ON e.id = i.event_pk WHERE e.user_id = :u"), {"u": body.user_id}).scalar_one()
        if ids:
            s.execute(text("DELETE FROM notification_outbox WHERE kind = 'event' AND ref_id = ANY(:ids)"), {"ids": ids})
        if alert_ids:
            s.execute(text("DELETE FROM notification_outbox WHERE kind = 'alert' AND ref_id = ANY(:ids)"), {"ids": alert_ids})
        s.execute(text("DELETE FROM alerts WHERE user_id = :u"), {"u": body.user_id})
        s.execute(text("DELETE FROM events WHERE user_id = :u"), {"u": body.user_id})  # cascata: análises e incidentes
        executive = s.execute(text("SELECT count(*) FROM reports WHERE kind IN ('executivo', 'piloto')")).scalar_one()
        result = {"events_deleted": len(ids), "incidents_deleted": incidents, "alerts_deleted": len(alert_ids),
                  "reports_to_review": executive,
                  "note": "Relatórios executivos já gerados podem listar a pessoa no ranking de indicador de risco: revise e apague com DELETE /v1/reports/{id}. "
                          "O registro de auditoria guarda só o hash do identificador."}
        audit.write(s, p, "privacy.subject_erase", "subject", subject_hash(body.user_id),
                    {"justification": body.justification, "events": len(ids), "incidents": incidents, "alerts": len(alert_ids)})
        return result


@router.post("/retention/run", summary="Roda a retenção agora para este tenant (o worker também roda uma vez por dia)")
def run_retention(p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        counts = retention.run(s, p.tenant_id, actor=p.id)
        return counts


@router.get("/data-map", summary="Quais dados o produto guarda e por quanto tempo, para este tenant (para o mapa de dados e o RIPD/DPIA)")
def data_map(p: Annotated[Principal, Depends(require_roles("admin", "auditor", "analista"))]) -> dict:
    from app.models import Tenant

    with tenant_session(p.tenant_id) as s:
        t = s.get(Tenant, p.tenant_id)
        assert t is not None
        n = lambda sql: s.execute(text(sql)).scalar_one()  # noqa: E731
        return {
            "retention_days": t.retention_days,
            "original_text_stored": t.store_original, "original_retention_days": min(t.original_retention_days, t.retention_days),
            "counts": {"events": n("SELECT count(*) FROM events"), "events_with_original": n("SELECT count(*) FROM events WHERE original_ciphertext IS NOT NULL"),
                       "distinct_monitored_people": n("SELECT count(DISTINCT user_id) FROM events"), "alerts": n("SELECT count(*) FROM alerts"),
                       "reports": n("SELECT count(*) FROM reports"), "console_users": n("SELECT count(*) FROM users"),
                       "oldest_event_received_at": (n("SELECT min(received_at) FROM events").isoformat() if n("SELECT count(*) FROM events") else None)},
            "last_retention_run": t.last_retention_run.isoformat() if t.last_retention_run else None,
            "audit_log": "imutável; sem texto de prompt; sem prazo automático de apagamento (ver docs/lgpd.md)",
        }
