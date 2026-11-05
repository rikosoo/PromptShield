"""Revisão humana da análise (falso positivo / faltou pegar) e medição de qualidade com dados reais.

Honestidade: as revisões não são uma amostra aleatória (quem revisa tende a olhar o que já foi sinalizado), então a "precisão estimada"
só vale como indicação. Para medir de verdade, revise uma amostra aleatória (docs/piloto.md)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from promptshield_detection.taxonomy import load as load_taxonomy
from sqlalchemy import func, select

from app import audit
from app.db import tenant_session
from app.models import Analysis, Event, EventFeedback
from app.routers.analytics import window_start
from app.schemas import FeedbackIn
from app.security import Principal, require_roles

router = APIRouter(prefix="/v1", tags=["qualidade"])
MIN_FOR_ESTIMATE = 5


def view(fb: EventFeedback | None) -> dict | None:
    if fb is None:
        return None
    return {"verdict": fb.verdict, "wrong_categories": fb.wrong_categories or [], "missing_categories": fb.missing_categories or [],
            "note": fb.note, "updated_at": fb.updated_at.isoformat()}


def feedback_for(s, event_pks: list[uuid.UUID]) -> dict[uuid.UUID, EventFeedback]:
    if not event_pks:
        return {}
    return {f.event_pk: f for f in s.execute(select(EventFeedback).where(EventFeedback.event_pk.in_(event_pks))).scalars()}


@router.post("/events/{event_id}/feedback", summary="Registra a revisão humana da análise deste evento (a última vale)")
def set_feedback(event_id: uuid.UUID, body: FeedbackIn, p: Annotated[Principal, Depends(require_roles("admin", "analista"))]) -> dict:
    tax = load_taxonomy()
    unknown = [c for c in body.wrong_categories + body.missing_categories if c not in tax]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"categoria fora da taxonomia: {unknown[0]}")
    with tenant_session(p.tenant_id) as s:
        row = s.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id).where(Event.event_id == event_id)).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evento não encontrado")
        ev, an = row
        reported = {c["id"] for c in an.categories}
        wrong = sorted(set(body.wrong_categories))
        missing = sorted(set(body.missing_categories))
        if body.verdict == "correta":
            wrong, missing = [], []
        if body.verdict == "falso_positivo" and not wrong:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "falso positivo: diga qual categoria sinalizada está errada")
        if body.verdict == "faltou" and not missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "faltou pegar: diga qual categoria deveria ter sido detectada")
        if set(wrong) - reported:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "só dá para marcar como errada uma categoria que foi sinalizada neste evento")
        if set(missing) & reported:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "a categoria que faltou já tinha sido sinalizada")
        fb = s.execute(select(EventFeedback).where(EventFeedback.event_pk == ev.id)).scalar()
        before = fb.verdict if fb else None
        if fb is None:
            fb = EventFeedback(tenant_id=p.tenant_id, event_pk=ev.id, verdict=body.verdict, reviewer_id=p.id)
            s.add(fb)
        fb.verdict, fb.wrong_categories, fb.missing_categories = body.verdict, wrong, missing
        fb.note, fb.reviewer_id, fb.updated_at = (body.note or None), p.id, datetime.now(timezone.utc)
        audit.write(s, p, "feedback.set", "event", str(event_id), {"before": before, "after": body.verdict, "wrong": wrong, "missing": missing})
        s.flush()
        return view(fb)  # type: ignore[return-value]


@router.get("/feedback/summary", summary="Quanto da análise foi revisada e onde ela erra (por categoria)")
def summary(p: Annotated[Principal, Depends(require_roles("admin", "analista", "auditor"))], days: int = Query(90, ge=1, le=365)) -> dict:
    since = window_start(days)
    with tenant_session(p.tenant_id) as s:
        total = s.execute(select(func.count()).select_from(Event).where(Event.occurred_at >= since)).scalar_one()
        rows = s.execute(select(EventFeedback, Analysis).join(Analysis, Analysis.event_pk == EventFeedback.event_pk)
                         .join(Event, Event.id == EventFeedback.event_pk).where(Event.occurred_at >= since)).all()
        verdicts = {"correta": 0, "falso_positivo": 0, "faltou": 0}
        per: dict[str, dict[str, int]] = {}
        for fb, an in rows:
            verdicts[fb.verdict] += 1
            for c in an.categories:
                d = per.setdefault(c["id"], {"reviewed": 0, "wrong": 0, "missed": 0})
                d["reviewed"] += 1
                d["wrong"] += c["id"] in (fb.wrong_categories or [])
            for c in fb.missing_categories or []:
                per.setdefault(c, {"reviewed": 0, "wrong": 0, "missed": 0})["missed"] += 1
        reviewed = len(rows)
    tax = load_taxonomy()
    cats = []
    for cid, d in sorted(per.items(), key=lambda kv: (-(kv[1]["wrong"] + kv[1]["missed"]), kv[0])):
        est = round(1 - d["wrong"] / d["reviewed"], 2) if d["reviewed"] >= MIN_FOR_ESTIMATE else None
        cats.append({"id": cid, "nome": tax[cid].nome if cid in tax else cid, **d, "precision_estimate": est})
    return {"days": days, "events": total, "reviewed": reviewed, "verdicts": verdicts,
            "coverage": round(reviewed / total, 4) if total else 0.0, "categories": cats, "min_for_estimate": MIN_FOR_ESTIMATE,
            "note": "Revisões não são amostra aleatória: use como indicação, não como medida. Estimativa só com pelo menos "
                    f"{MIN_FOR_ESTIMATE} revisões da categoria."}


@router.get("/feedback/export.jsonl", summary="Exporta as revisões (texto mascarado, sem a nota do revisor) para montar um conjunto de avaliação; auditado")
def export_jsonl(p: Annotated[Principal, Depends(require_roles("admin", "auditor"))], days: int = Query(90, ge=1, le=365),
                 limit: int = Query(5000, ge=1, le=20000)) -> Response:
    since = window_start(days)
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(EventFeedback, Event, Analysis).join(Event, Event.id == EventFeedback.event_pk)
                         .join(Analysis, Analysis.event_pk == Event.id).where(Event.occurred_at >= since)
                         .order_by(EventFeedback.updated_at.desc()).limit(limit)).all()
        audit.write(s, p, "export.feedback_jsonl", "feedback", None, {"days": days, "rows": len(rows)})
        lines = []
        for fb, ev, an in rows:
            reported = {c["id"] for c in an.categories}
            expected = sorted((reported - set(fb.wrong_categories or [])) | set(fb.missing_categories or []))
            lines.append(json.dumps({"id": str(ev.event_id), "kind": ev.kind, "app": ev.app, "text": ev.masked_text, "reported": sorted(reported),
                                     "verdict": fb.verdict, "expected": expected, "label_source": "revisao_humana"}, ensure_ascii=False))
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="revisoes.jsonl"'})
