from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from promptshield_detection.scoring import severity_for
from sqlalchemy import Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import cast

from app import audit, crypto
from app.csvsafe import csv_safe
from app.db import tenant_session
from app.models import Analysis, Device, Event, EventFeedback, Incident
from app.routers.analytics import window_start
from app.routers.feedback import feedback_for, view
from app.schemas import EventIn, EventResult, JustificationIn, OriginalRequest
from app.security import READ_ROLES, Principal, require_ingest, require_roles
from app.services import ingest, v2_view

router = APIRouter(prefix="/v1/events", tags=["eventos"])


@router.post("", response_model=EventResult, summary="Recebe um evento universal, analisa e devolve a decisão")
def post_event(ev: EventIn, p: Annotated[Principal, Depends(require_ingest)]) -> EventResult:
    with tenant_session(p.tenant_id) as s:
        return ingest(s, p, ev)


def event_filters(
    user_id: str | None = None,
    user_q: str | None = Query(None, min_length=1, max_length=100, description="parte do nome/e-mail da pessoa"),
    min_score: int = Query(0, ge=0, le=100),
    category: str | None = Query(None, description="id da categoria da taxonomia"),
    has_code: bool | None = None, has_sensitive: bool | None = None, agent_action: bool | None = None,
    only_blocked: bool = Query(False, description="decisão block, ou que seria block em modo monitorar"),
    decision: str | None = Query(None, pattern="^(allow|mask|block|ask_justification|alert)$", description="decisão tomada ou que seria tomada"),
    kind: str | None = Query(None, pattern="^(prompt|response|tool_call|tool_result|file_upload)$"),
    search: str | None = Query(None, alias="q", min_length=2, max_length=100, description="busca no texto JÁ mascarado (nunca no original)"),
    sensor: Annotated[uuid.UUID | None, Query(description="id do sensor (dispositivo): só os eventos enviados pela chave dele")] = None,
    has_attachment: bool | None = Query(None, description="o prompt veio com arquivo anexado"),
    severity: str | None = Query(None, pattern="^(baixo|medio|alto|critico)$", description="faixa do score: baixo 0-24, medio 25-49, alto 50-69, critico 70-100"),
    alert_status: str | None = Query(None, pattern="^(sem_alerta|novo|em_analise|falso_positivo|resolvido)$", description="situação do alerta (incidente) do prompt"),
    review: str | None = Query(None, pattern="^(pending|reviewed|correta|falso_positivo|faltou)$", description="revisão humana da análise"),
    span_type: str | None = Query(None, max_length=40, description="tipo de trecho sensível detectado (ex.: aws_access_key, cpf)"),
    intent: str | None = Query(None, max_length=40, description="o que a pessoa pediu (ex.: resumir, declara_confidencial)"),
    session_id: str | None = Query(None, max_length=200),
    department: str | None = None, app: str | None = None, personal_account: bool | None = None,
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
    date_from: Annotated[date | None, Query(description="a partir deste dia (UTC, inclusive)")] = None,
    date_to: Annotated[date | None, Query(description="até este dia (UTC, inclusive)")] = None,
) -> dict:
    return {k: v for k, v in locals().items()}


def _like(text_value: str) -> str:
    return "%" + text_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def apply_filters(q, f: dict):
    q = q.where(Analysis.risk_score >= f["min_score"])
    if f["user_id"]:
        q = q.where(Event.user_id == f["user_id"])
    if f["user_q"]:
        q = q.where(Event.user_id.ilike(_like(f["user_q"]), escape="\\"))
    if f["department"]:
        q = q.where(Event.department == f["department"])
    if f["app"]:
        q = q.where(Event.app == f["app"])
    if f["personal_account"] is not None:
        q = q.where(Event.personal_account.is_(f["personal_account"]))
    if f["days"]:
        q = q.where(Event.occurred_at >= window_start(f["days"]))
    if f["date_from"]:
        q = q.where(Event.occurred_at >= datetime.combine(f["date_from"], time.min, tzinfo=timezone.utc))
    if f["date_to"]:
        q = q.where(Event.occurred_at < datetime.combine(f["date_to"] + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if f["category"]:
        q = q.where(cast(Analysis.categories, JSONB).contains([{"id": f["category"]}]))
    for key, flag in (("has_code", f["has_code"]), ("has_sensitive", f["has_sensitive"]), ("is_agent_action", f["agent_action"])):
        if flag is not None:
            q = q.where(cast(Analysis.flags, JSONB).contains({key: flag}))
    if f["only_blocked"]:
        q = q.where((Analysis.decision == "block") | (Analysis.would_decide == "block"))
    if f["decision"]:
        q = q.where((Analysis.decision == f["decision"]) | (Analysis.would_decide == f["decision"]))
    if f["severity"]:
        lo, hi = SEVERITY_RANGE[f["severity"]]
        q = q.where(Analysis.risk_score >= lo, Analysis.risk_score <= hi)
    if f["alert_status"]:
        if f["alert_status"] == "sem_alerta":
            inc = aliased(Incident)
            q = q.where(~select(inc.id).where(inc.event_pk == Event.id).exists())
        else:
            wanted = next(k for k, v in ALERT_STATUS.items() if v == f["alert_status"])
            inc = aliased(Incident)
            q = q.where(select(inc.id).where(inc.event_pk == Event.id, inc.status == wanted).exists())
    if f["kind"]:
        q = q.where(Event.kind == f["kind"])
    if f["session_id"]:
        q = q.where(Event.session_id == f["session_id"])
    if f["search"]:
        q = q.where(Event.masked_text.ilike(_like(f["search"]), escape="\\")
                    | cast(Event.attachments, JSONB).cast(Text).ilike(_like(f["search"]), escape="\\"))   # também acha pelo nome do arquivo
    if f["sensor"]:
        q = q.where(Event.api_key_id == select(Device.api_key_id).where(Device.id == f["sensor"]).scalar_subquery())
    if f["review"]:
        rv = select(EventFeedback.id).where(EventFeedback.event_pk == Event.id)
        if f["review"] in ("correta", "falso_positivo", "faltou"):
            rv = rv.where(EventFeedback.verdict == f["review"])
        q = q.where(~rv.exists() if f["review"] == "pending" else rv.exists())
    if f["has_attachment"] is not None:
        has = cast(Event.attachments, JSONB).contains([{}])   # algum elemento-objeto: vale para NULL, null e [] (sem arquivos)
        q = q.where(has if f["has_attachment"] else ~has)
    if f["span_type"]:
        q = q.where(cast(Analysis.spans, JSONB).contains([{"type": f["span_type"]}]))
    if f["intent"]:
        q = q.where(cast(Analysis.flags, JSONB).contains({"intents": [f["intent"]]}))
    return q


@router.get("", summary="Lista eventos (texto sempre mascarado); filtros para a análise de prompts. Total no header X-Total-Count")
def list_events(
    response: Response,
    p: Annotated[Principal, Depends(require_roles(*READ_ROLES))],
    f: Annotated[dict, Depends(event_filters)],
    sort: str = Query("recent", pattern="^(recent|risk)$"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        q = apply_filters(select(Event, Analysis, Incident.id, Incident.status).join(Analysis, Analysis.event_pk == Event.id)
                          .outerjoin(Incident, Incident.event_pk == Event.id), f)
        total = s.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        order = (Analysis.risk_score.desc(), Event.occurred_at.desc()) if sort == "risk" else (Event.occurred_at.desc(), Event.id.desc())
        rows = s.execute(q.order_by(*order).limit(limit).offset(offset)).all()
        response.headers["X-Total-Count"] = str(total)
        fbs = feedback_for(s, [e.id for e, _, _, _ in rows])
        return [_view(e, a, i, fbs.get(e.id), st) for e, a, i, st in rows]


@router.get("/export.csv", response_class=PlainTextResponse, summary="Exporta em CSV (texto mascarado) com os mesmos filtros; a exportação é auditada")
def export_csv(
    p: Annotated[Principal, Depends(require_roles("admin", "auditor"))],
    f: Annotated[dict, Depends(event_filters)],
    limit: int = Query(5000, ge=1, le=20000),
) -> Response:
    with tenant_session(p.tenant_id) as s:
        q = apply_filters(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id), f)
        rows = s.execute(q.order_by(Event.occurred_at.desc(), Event.id.desc()).limit(limit)).all()
        used = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in f.items() if v not in (None, False, 0)}
        audit.write(s, p, "export.prompts_csv", "events", None, {"filters": used, "rows": len(rows)})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["quando_utc", "pessoa", "departamento", "ferramenta", "tipo", "categorias", "pedido", "arquivos", "score", "decisao", "teria_decidido", "texto_mascarado"])
        for e, a in rows:
            w.writerow([e.occurred_at.isoformat(), csv_safe(e.user_id), csv_safe(e.department), e.app, e.kind,
                        ";".join(c["id"] for c in a.categories), ";".join((a.flags or {}).get("intents", [])),
                        csv_safe("; ".join(x.get("name", "") for x in (e.attachments or []))), a.risk_score,
                        a.decision, a.would_decide, csv_safe(e.masked_text)])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="prompts.csv"'})


@router.get("/{event_id}", summary="Detalhe de um evento (texto mascarado)")
def get_event(event_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        row = s.execute(select(Event, Analysis, Incident.id, Incident.status).join(Analysis, Analysis.event_pk == Event.id)
                        .outerjoin(Incident, Incident.event_pk == Event.id).where(Event.event_id == event_id)).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evento não encontrado")
        e, a, inc, inc_status = row
        out = _view(e, a, inc, feedback_for(s, [e.id]).get(e.id), inc_status)
        out["analysis_v2"] = v2_view(a, e.masked_text)        # só no detalhe: o resultado padronizado completo (achados, impacto, recomendação)
        return out


@router.post("/{event_id}/justification", status_code=204,
             summary="Registra a justificativa do usuário para enviar mesmo assim (política ask_justification)")
def post_justification(event_id: uuid.UUID, body: JustificationIn, p: Annotated[Principal, Depends(require_ingest)]) -> None:
    with tenant_session(p.tenant_id) as s:
        if s.execute(select(Event.id).where(Event.event_id == event_id)).scalar() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evento não encontrado")
        audit.write(s, p, "event.justification", "event", str(event_id), {"justification": body.justification})


@router.post("/{event_id}/original", summary="Lê o texto original (exige justificativa; grava auditoria)")
def read_original(event_id: uuid.UUID, body: OriginalRequest,
                  p: Annotated[Principal, Depends(require_roles("admin", "analista"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        ev = s.execute(select(Event).where(Event.event_id == event_id)).scalar()
        if ev is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evento não encontrado")
        # o pedido fica registrado mesmo quando não há original guardado
        audit.write(s, p, "event.original_read", "event", str(event_id),
                    {"justification": body.justification, "available": ev.original_ciphertext is not None})
        if ev.original_ciphertext is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "este tenant não guarda o texto original deste evento")
        return {"event_id": str(event_id), "text": crypto.decrypt_original(p.tenant_id, ev.original_ciphertext)}


SEVERITY_RANGE = {"baixo": (0, 24), "medio": (25, 49), "alto": (50, 69), "critico": (70, 100)}
ALERT_STATUS = {"aberto": "novo", "em analise": "em_analise", "falso positivo": "falso_positivo", "resolvido": "resolvido"}


def _view(e: Event, a: Analysis, incident_id: uuid.UUID | None = None, fb: EventFeedback | None = None, incident_status: str | None = None) -> dict:
    return {"event_id": str(e.event_id), "occurred_at": e.occurred_at.isoformat(), "app": e.app, "channel": e.channel,
            "user_id": e.user_id, "department": e.department, "kind": e.kind, "personal_account": e.personal_account,
            "masked_text": e.masked_text, "attachments": e.attachments or [], "has_original": e.original_ciphertext is not None, "tool_name": e.tool_name,
            "session_id": e.session_id, "spans": [{"type": sp.get("type"), "masked": sp.get("masked")} for sp in (a.spans or [])],
            "categories": a.categories, "flags": a.flags, "risk_score": a.risk_score, "reasons": a.reasons,
            "decision": a.decision, "would_decide": a.would_decide, "policy_hits": a.policy_hits,
            "incident_id": str(incident_id) if incident_id else None, "feedback": view(fb),
            # monitoramento passivo: severidade pelas faixas 0-24 baixo, 25-49 medio, 50-69 alto, 70-100 critico; status do alerta no lugar da "decisão"
            "severity": severity_for(a.risk_score), "alert_status": ALERT_STATUS.get(incident_status or "", "sem_alerta"),
            "findings": a.findings or [], "engine_version": a.engine_version}
