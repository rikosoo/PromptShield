"""Ingestão: valida, analisa (motor), aplica políticas, grava texto mascarado e análise, abre incidente."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from promptshield_detection import analyze
from promptshield_detection.output import to_v2
from promptshield_detection.scoring import CRITICAL_MIN, HIGH_RISK_MIN, severity_for
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import alerts, crypto, governance, metrics
from app.config import settings
from app.keywords import matcher
from app.models import Analysis, Event, Incident, KeywordRule, Policy, Tenant
from app.policy_engine import DEFAULT_POLICIES, PolicySpec, Subject, evaluate
from app.schemas import EventIn, EventResult, SpanOut
from app.security import Principal

INCIDENT_MIN_SCORE = HIGH_RISK_MIN     # faixa "alto" (50) em diante abre incidente; abaixo disso é só registro e, no máximo, alerta informativo
_ner: Any = None


def init_ner() -> None:
    """Liga o NER opcional (Presidio + spaCy) se ENABLE_NER=true. Falha alto se o pedido não puder ser atendido."""
    global _ner
    if settings.enable_ner and _ner is None:
        from promptshield_detection.ner import NerDetector

        _ner = NerDetector()


def severity(score: int) -> str:
    """Severidade do incidente (só existe de "alto" em diante): 50-69 alto, 70-100 crítico."""
    return "critico" if score >= CRITICAL_MIN else "alto"


def severity_label(score: int) -> str:
    """Faixas do painel: 0-24 baixo, 25-49 medio (moderado), 50-69 alto, 70-100 critico."""
    return severity_for(score)


def v2_view(a: Analysis, masked_text: str) -> dict:
    """Resultado padronizado v2 a partir do que está guardado. Análises antigas (sem achados) viram achados por categoria."""
    findings = a.findings or [{"type": c["id"], "category": c["id"], "confidence": c["confidence"], "rule": "Categoria detectada (análise anterior ao motor 2.0)",
                               "evidence": None} for c in a.categories]
    return to_v2(risk_score=a.risk_score, categories=a.categories, findings=findings, masked_prompt=masked_text, reasons=a.reasons or [],
                 engine_version=a.engine_version or "1.x")


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
        spans=[SpanOut(**s) for s in an.spans], policy_hits=an.policy_hits, incident_id=incident_id, duplicate=duplicate,
        analysis_v2=v2_view(an, event.masked_text))


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
    an = analyze(_engine_event(ev), ner=_ner, allowed_hosts=governance.allowed_hosts(session), weights=tenant.risk_weights or None)

    kw_hits = matcher.find(text, [matcher.Rule(str(k.id), k.term, k.whole_word, k.score) for k in
                                  session.execute(select(KeywordRule).where(KeywordRule.enabled.is_(True))).scalars()])
    if kw_hits:
        calculated = an.risk["score"]
        final = matcher.effective_score(calculated, kw_hits)
        if final != calculated:       # pontuação escolhida pelo administrador substitui a calculada; o motivo fica registrado
            an.risk["score"] = final
            chosen = max((r for r in kw_hits if r.score is not None), key=lambda r: r.score or 0)
            an.risk["reasons"] = [*an.risk["reasons"], {"rule": f"Palavra-chave «{chosen.term}»: pontuação definida pelo administrador (calculada: {calculated})",
                                                        "contribution": final - calculated}]

    exceptions = governance.active_exceptions(session)
    specs = [PolicySpec(id=str(x.id), name=x.name, action=x.action, mode=x.mode, enabled=x.enabled,
                        scope=x.scope or {}, match=x.match or {}, exceptions=exceptions.get(str(x.id), ()))
             for x in session.execute(select(Policy).where(Policy.enabled.is_(True))).scalars()]
    subject = Subject(ev.actor.department, ev.source.app, tuple(ev.actor.groups), ev.actor.user_id,
                      governance.member_groups(session, ev.actor.user_id))
    pe = evaluate(specs, subject, an.categories, an.risk["score"])

    if force_monitor or settings.passive_only:      # passivo: o coletor recebe sempre "allow"; `would_decide` guarda o que a política teria feito
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
        reasons=an.risk["reasons"], findings=an.findings, engine_version=an.engine_version, spans=[{"start": s.start, "end": s.end, "type": s.type, "masked": s.masked} for s in an.spans],
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
    alerts.evaluate(session, tenant, event, analysis, incident_id, severity(an.risk["score"]) if incident_id else None,
                    keyword_hits=[(r.id, r.term, r.score) for r in kw_hits])
    return _result(event, analysis, incident_id, False)
