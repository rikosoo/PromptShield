"""Ingestão: valida, analisa (motor), aplica políticas, grava texto mascarado e análise, abre incidente."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from promptshield_detection import analyze
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import alerts, crypto, governance, metrics
from app.config import settings
from app.models import Analysis, Event, Incident, Policy, Tenant
from app.policy_engine import DEFAULT_POLICIES, PolicySpec, Subject, evaluate
from app.schemas import EventIn, EventResult, SpanOut
from app.security import Principal

INCIDENT_MIN_SCORE = 60
_ner: Any = None


def init_ner() -> None:
    """Liga o NER opcional (Presidio + spaCy) se ENABLE_NER=true. Falha alto se o pedido não puder ser atendido."""
    global _ner
    if settings.enable_ner and _ner is None:
        from promptshield_detection.ner import NerDetector

        _ner = NerDetector()


def severity(score: int) -> str:
    return "critico" if score >= 80 else "alto"


def seed_default_policies(session: Session, tenant_id: uuid.UUID) -> None:
    for p in DEFAULT_POLICIES:
        session.add(Policy(tenant_id=tenant_id, name=p["name"], action=p["action"], match=p["match"], scope={},
                           mode="monitor", enabled=True))


OMIT_CONFIDENCE = 0.5


def stored_text(tenant: Tenant, an: Any) -> str:
    """Texto que vai para `events.masked_text`. Para categorias que o tenant escolheu não guardar (saúde por padrão: o mascaramento
    só cobre identificadores estruturados, não texto livre sensível), guarda um aviso no lugar do texto."""
    omit = set(tenant.omit_text_categories or [])
    hit = [c["id"] for c in an.categories if c["id"] in omit and c["confidence"] >= OMIT_CONFIDENCE]
    if not hit:
        return an.masked_text
    from promptshield_detection.taxonomy import load as load_taxonomy

    tax = load_taxonomy()
    return "[texto não guardado: categoria " + ", ".join(tax[c].nome if c in tax else c for c in hit) + "]"


def _engine_event(ev: EventIn) -> dict[str, Any]:
    return {"kind": ev.kind,
            "content": {"text": ev.content.text, "tool_name": ev.content.tool_name, "tool_input": ev.content.tool_input,
                        "attachments": [a.model_dump() for a in ev.content.attachments]},
            "context": {"personal_account": ev.context.personal_account}}


def _result(event: Event, an: Analysis, incident_id: uuid.UUID | None, duplicate: bool) -> EventResult:
    return EventResult(
        event_id=event.event_id, decision=an.decision, would_decide=an.would_decide,  # type: ignore[arg-type]
        enforced=an.decision != "allow" or an.would_decide == "allow",
        masked_text=event.masked_text, categories=an.categories, flags=an.flags,
        risk={"score": an.risk_score, "reasons": an.reasons, "score_version": an.score_version},
        spans=[SpanOut(**s) for s in an.spans], policy_hits=an.policy_hits, incident_id=incident_id, duplicate=duplicate)


def _existing(session: Session, event_id: uuid.UUID) -> EventResult | None:
    row = session.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id)
                          .where(Event.event_id == event_id)).first()
    if row is None:
        return None
    ev, an = row
    inc = session.execute(select(Incident.id).where(Incident.event_pk == ev.id)).scalar()
    return _result(ev, an, inc, True)


def ingest(session: Session, p: Principal, ev: EventIn, force_monitor: bool = False) -> EventResult:
    """`force_monitor`: grava a decisão que a política tomaria (`would_decide`), mas devolve `allow` (modo sombra do coletor)."""
    if ev.tenant_id is not None and ev.tenant_id != p.tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant_id do evento não corresponde ao da chave de API")
    text = ev.content.text
    if text is None and ev.content.tool_input:
        text = str(ev.content.tool_input.get("command") or "")
    text = text or ""
    if len(text) > settings.max_text_chars:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"texto acima de {settings.max_text_chars} caracteres")

    dup = _existing(session, ev.event_id)
    if dup is not None:
        return dup

    tenant = session.get(Tenant, p.tenant_id)
    assert tenant is not None
    an = analyze(_engine_event(ev), ner=_ner, allowed_hosts=governance.allowed_hosts(session))

    exceptions = governance.active_exceptions(session)
    specs = [PolicySpec(id=str(x.id), name=x.name, action=x.action, mode=x.mode, enabled=x.enabled,
                        scope=x.scope or {}, match=x.match or {}, exceptions=exceptions.get(str(x.id), ()))
             for x in session.execute(select(Policy).where(Policy.enabled.is_(True))).scalars()]
    subject = Subject(ev.actor.department, ev.source.app, tuple(ev.actor.groups), ev.actor.user_id,
                      governance.member_groups(session, ev.actor.user_id))
    pe = evaluate(specs, subject, an.categories, an.risk["score"])

    if force_monitor:
        pe.decision = "allow"
    original = None
    if tenant.store_original and text:
        try:
            original = crypto.encrypt_original(p.tenant_id, text)
        except crypto.MasterKeyMissingError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                                "o tenant guarda texto original, mas a chave mestra não está configurada") from exc

    stmt = insert(Event).values(
        id=uuid.uuid4(), tenant_id=p.tenant_id, event_id=ev.event_id, occurred_at=ev.occurred_at,
        channel=ev.source.channel, app=ev.source.app, integration_status=ev.source.integration_status,
        user_id=ev.actor.user_id, department=ev.actor.department, device_id=ev.actor.device_id,
        agent_id=ev.actor.agent_id, kind=ev.kind, session_id=ev.context.session_id,
        personal_account=ev.context.personal_account, tool_name=ev.content.tool_name,
        api_key_id=uuid.UUID(p.id) if p.kind == "api_key" else None, masked_text=stored_text(tenant, an), text_length=len(text), original_ciphertext=original, attachments=an.attachments,
    ).on_conflict_do_nothing(index_elements=["tenant_id", "event_id"]).returning(Event.id)
    pk = session.execute(stmt).scalar()
    if pk is None:  # corrida: outro pedido gravou o mesmo event_id
        dup = _existing(session, ev.event_id)
        assert dup is not None
        return dup

    analysis = Analysis(
        tenant_id=p.tenant_id, event_pk=pk, categories=an.categories, flags=an.flags, risk_score=an.risk["score"],
        reasons=an.risk["reasons"], spans=[{"start": s.start, "end": s.end, "type": s.type, "masked": s.masked} for s in an.spans],
        decision=pe.decision, would_decide=pe.would_decide, policy_hits=pe.hits, score_version=an.score_version)
    session.add(analysis)
    incident_id = None
    if an.risk["score"] >= INCIDENT_MIN_SCORE:
        inc = Incident(tenant_id=p.tenant_id, event_pk=pk, severity=severity(an.risk["score"]))
        session.add(inc)
        session.flush()
        incident_id = inc.id
    session.flush()
    event = session.get(Event, pk)
    assert event is not None
    metrics.inc("ps_events_ingested_total", channel=ev.source.channel, decision=analysis.decision)
    alerts.evaluate(session, tenant, event, analysis, incident_id, severity(an.risk["score"]) if incident_id else None)
    return _result(event, analysis, incident_id, False)
