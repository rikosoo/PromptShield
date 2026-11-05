"""Regras de alerta avaliadas na ingestão, com deduplicação, e fila de envio (outbox).

Deduplicação: cada alerta tem uma chave (regra, usuário, categoria, janela). A mesma chave só incrementa `count`;
a notificação sai uma única vez, quando o alerta é criado.
"""
from __future__ import annotations

import uuid
from datetime import timedelta, timezone
from typing import Any

from promptshield_detection.taxonomy import load as load_taxonomy
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Alert, Analysis, Event, NotificationChannel, OutboxItem, Tenant

ALERT_KINDS = ("webhook", "slack", "teams", "email")
EVENT_KINDS = ("syslog_cef", "siem_webhook")
SEVERITY_ORDER = {"baixo": 0, "medio": 1, "alto": 2, "critico": 3}
INJECTION_CATEGORIES = ("injection_direta", "injection_indireta", "jailbreak")
INJECTION_MIN_CONFIDENCE = 0.8
AGENT_CATEGORIES = ("shell_destrutivo", "leitura_env", "rede_externa", "escrita_fora_projeto", "instalacao_pacote",
                    "alteracao_permissao", "exfiltracao_ferramenta")
AGENT_MIN_SCORE = 35
AGENT_MIN_BASELINE_EVENTS = 20  # sem histórico mínimo, "fora do padrão" não significa nada
AGENT_BASELINE_DAYS = 14
DEFAULT_ALERT_MIN_SEVERITY = "medio"
DEFAULT_EVENT_MIN_SCORE = 35

RULE_LABELS = {"severidade": "Evento de risco alto ou crítico", "injection": "Tentativa de injection com confiança alta",
               "volume": "Volume anormal de uso por usuário", "agente": "Ação de agente fora do padrão"}


def _name(cid: str) -> str:
    c = load_taxonomy().get(cid)
    return c.nome if c else cid


def _upsert(session: Session, tenant: Tenant, ev: Event, rule: str, severity: str, key: str, title: str,
            detail: dict[str, Any], incident_id: uuid.UUID | None) -> Alert | None:
    """Cria o alerta ou incrementa o existente. Devolve o alerta só se foi CRIADO agora (para notificar uma vez)."""
    stmt = insert(Alert).values(
        id=uuid.uuid4(), tenant_id=tenant.id, rule=rule, severity=severity, dedup_key=key, user_id=ev.user_id,
        department=ev.department, event_pk=ev.id, incident_id=incident_id, title=title, detail=detail, count=1,
        first_seen=func.now(), last_seen=func.now())
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "dedup_key"],
        set_={"count": Alert.count + 1, "last_seen": func.now()}).returning(Alert.id, literal_column("(xmax = 0)").label("inserted"))
    row = session.execute(stmt).one()
    if not row.inserted:
        return None
    return session.get(Alert, row.id)


def _enqueue(session: Session, tenant_id: uuid.UUID, channels: list[NotificationChannel], kind: str, ref_id: uuid.UUID) -> None:
    for ch in channels:
        session.execute(insert(OutboxItem).values(tenant_id=tenant_id, channel_id=ch.id, kind=kind, ref_id=ref_id)
                        .on_conflict_do_nothing(index_elements=["channel_id", "kind", "ref_id"]))


def evaluate(session: Session, tenant: Tenant, ev: Event, an: Analysis, incident_id: uuid.UUID | None,
             incident_severity: str | None) -> list[Alert]:
    """Avalia as regras para um evento recém-gravado. Devolve os alertas CRIADOS (não os repetidos)."""
    day = ev.occurred_at.astimezone(timezone.utc).strftime("%Y%m%d")
    cats = {c["id"]: c["confidence"] for c in an.categories}
    top = an.categories[0]["id"] if an.categories else "geral"
    created: list[Alert] = []

    def add(rule: str, severity: str, key: str, title: str, detail: dict[str, Any]) -> None:
        a = _upsert(session, tenant, ev, rule, severity, key, title, detail, incident_id)
        if a is not None:
            created.append(a)

    base = {"score": an.risk_score, "categories": [c["id"] for c in an.categories], "event_id": str(ev.event_id)}

    if incident_id is not None and incident_severity in ("alto", "critico"):
        add("severidade", incident_severity, f"sev:{ev.user_id}:{top}:{day}",
            f"{RULE_LABELS['severidade']}: {_name(top) if top != 'geral' else 'geral'}", base)

    for cid in INJECTION_CATEGORIES:
        if cats.get(cid, 0) >= INJECTION_MIN_CONFIDENCE:
            add("injection", "alto", f"inj:{ev.user_id}:{cid}:{day}", f"{RULE_LABELS['injection']}: {_name(cid)}",
                {**base, "confidence": cats[cid]})

    threshold = tenant.volume_threshold_per_hour
    if threshold > 0:
        hour_start = ev.occurred_at.replace(minute=0, second=0, microsecond=0)
        n = session.execute(select(func.count()).select_from(Event).where(
            Event.user_id == ev.user_id, Event.occurred_at >= hour_start, Event.occurred_at < hour_start + timedelta(hours=1))).scalar_one()
        if n > threshold:
            add("volume", "medio", f"vol:{ev.user_id}:{hour_start.strftime('%Y%m%d%H')}",
                f"{RULE_LABELS['volume']}: mais de {threshold} eventos em uma hora", {**base, "events_in_hour": n, "threshold": threshold})

    agent_cats = [c for c in cats if c in AGENT_CATEGORIES and cats[c] >= 0.5]
    if agent_cats and an.flags.get("is_agent_action") and an.risk_score >= AGENT_MIN_SCORE:
        since = ev.occurred_at - timedelta(days=AGENT_BASELINE_DAYS)
        history = session.execute(select(func.count()).select_from(Event).where(
            Event.user_id == ev.user_id, Event.occurred_at >= since, Event.id != ev.id)).scalar_one()
        if history >= AGENT_MIN_BASELINE_EVENTS:
            for cid in agent_cats:
                seen = session.execute(
                    select(func.count()).select_from(Event).join(Analysis, Analysis.event_pk == Event.id).where(
                        Event.user_id == ev.user_id, Event.occurred_at >= since, Event.id != ev.id,
                        text("(analyses.categories::jsonb) @> CAST(:c AS jsonb)")).params(c=f'[{{"id": "{cid}"}}]')).scalar_one()
                if seen == 0:
                    wk = ev.occurred_at.isocalendar()
                    add("agente", "alto", f"agt:{ev.user_id}:{cid}:{wk.year}W{wk.week:02d}",
                        f"{RULE_LABELS['agente']}: {_name(cid)} (sem ocorrência nos {AGENT_BASELINE_DAYS} dias anteriores)",
                        {**base, "baseline_events": history})

    if created:
        channels = [c for c in session.execute(select(NotificationChannel).where(
            NotificationChannel.enabled.is_(True), NotificationChannel.kind.in_(ALERT_KINDS))).scalars()]
        for a in created:
            eligible = [c for c in channels if SEVERITY_ORDER[a.severity] >=
                        SEVERITY_ORDER.get((c.config or {}).get("min_severity", DEFAULT_ALERT_MIN_SEVERITY), 1)]
            _enqueue(session, tenant.id, eligible, "alert", a.id)

    stream = [c for c in session.execute(select(NotificationChannel).where(
        NotificationChannel.enabled.is_(True), NotificationChannel.kind.in_(EVENT_KINDS))).scalars()
        if an.risk_score >= (c.config or {}).get("min_score", DEFAULT_EVENT_MIN_SCORE)]
    if stream:
        _enqueue(session, tenant.id, stream, "event", ev.id)
    return created
