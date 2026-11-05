"""Registro de evento para SIEM (sem o texto do prompt) e título do evento."""
from __future__ import annotations

from typing import Any

from promptshield_detection.taxonomy import load as load_taxonomy

from app.models import Analysis, Event


def event_record(e: Event, a: Analysis) -> dict[str, Any]:
    tax = load_taxonomy()
    top = a.categories[0]["id"] if a.categories else None
    title = f"{tax[top].nome}" if top in tax else "Evento de uso de IA"
    return {"event_id": str(e.event_id), "occurred_at": e.occurred_at, "user_id": e.user_id, "department": e.department,
            "app": e.app, "channel": e.channel, "kind": e.kind, "personal_account": e.personal_account,
            "categories": a.categories, "risk_score": a.risk_score, "reasons": a.reasons, "decision": a.decision,
            "would_decide": a.would_decide, "score_version": a.score_version, "title": title}


def json_safe(rec: dict[str, Any]) -> dict[str, Any]:
    return {**rec, "occurred_at": rec["occurred_at"].isoformat()}
