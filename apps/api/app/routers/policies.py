from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app import audit
from app.db import tenant_session
from app.models import Analysis, Event, Policy
from app.policy_engine import RANK, PolicySpec, Subject, evaluate
from app.routers.analytics import window_start
from app.schemas import PolicyIn, PolicyOut
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1/policies", tags=["políticas"])


def _out(p: Policy) -> PolicyOut:
    return PolicyOut(id=p.id, name=p.name, description=p.description, enabled=p.enabled, scope=p.scope or {}, match=p.match or {},
                     action=p.action, mode=p.mode, version=p.version, updated_at=p.updated_at)  # type: ignore[arg-type]


def _snapshot(p: Policy) -> dict:
    return {"name": p.name, "enabled": p.enabled, "scope": p.scope, "match": p.match, "action": p.action, "mode": p.mode, "version": p.version}


@router.get("", response_model=list[PolicyOut])
def list_policies(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> list[PolicyOut]:
    with tenant_session(p.tenant_id) as s:
        return [_out(x) for x in s.execute(select(Policy).order_by(Policy.name)).scalars()]


@router.post("", response_model=PolicyOut, status_code=201, summary="Cria política (nasce em modo monitor por padrão)")
def create_policy(body: PolicyIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> PolicyOut:
    with tenant_session(p.tenant_id) as s:
        pol = Policy(tenant_id=p.tenant_id, **body.model_dump())
        s.add(pol)
        s.flush()
        audit.write(s, p, "policy.create", "policy", str(pol.id), {"after": _snapshot(pol)})
        s.refresh(pol)
        return _out(pol)


@router.put("/{policy_id}", response_model=PolicyOut, summary="Altera política (grava auditoria com antes e depois)")
def update_policy(policy_id: uuid.UUID, body: PolicyIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> PolicyOut:
    with tenant_session(p.tenant_id) as s:
        pol = s.get(Policy, policy_id)
        if pol is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "política não encontrada")
        before = _snapshot(pol)
        for k, v in body.model_dump().items():
            setattr(pol, k, v)
        pol.version += 1
        s.execute(text("UPDATE policies SET updated_at = now() WHERE id = :i"), {"i": policy_id})
        s.flush()
        audit.write(s, p, "policy.update", "policy", str(policy_id), {"before": before, "after": _snapshot(pol)})
        s.refresh(pol)
        return _out(pol)


class SimulateIn(BaseModel):
    policy: PolicyIn
    days: int = Field(default=30, ge=1, le=90)


MAX_SIMULATED = 5000


@router.post("/simulate", summary="Simula uma política sobre os eventos passados, sem salvar nada")
def simulate(body: SimulateIn, p: Annotated[Principal, Depends(require_roles("admin", "analista"))]) -> dict:
    spec = PolicySpec(id="simulada", name=body.policy.name, action=body.policy.action, mode=body.policy.mode, enabled=True,
                      scope=body.policy.scope, match=body.policy.match)
    since = window_start(body.days)
    with tenant_session(p.tenant_id) as s:
        total = s.execute(select(text("count(*)")).select_from(Event).where(Event.occurred_at >= since)).scalar_one()
        rows = s.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id).where(Event.occurred_at >= since)
                         .order_by(Event.occurred_at.desc()).limit(MAX_SIMULATED)).all()
        matched, users, stronger, examples = 0, set(), 0, []
        for e, a in rows:
            ev = evaluate([spec], Subject(e.department, e.app, ()), a.categories, a.risk_score)
            if not ev.hits:
                continue
            matched += 1
            users.add(e.user_id)
            if RANK[spec.action] > RANK[a.would_decide]:
                stronger += 1
            if len(examples) < 5:
                examples.append({"event_id": str(e.event_id), "user_id": e.user_id, "risk_score": a.risk_score,
                                 "masked_text": e.masked_text[:200], "current_decision": a.decision})
    return {"days": body.days, "events_in_period": total, "events_evaluated": len(rows), "truncated": total > len(rows),
            "matched": matched, "matched_users": len(users), "would_be_stronger_than_current": stronger, "examples": examples,
            "action": spec.action, "mode": spec.mode,
            "ignored_scope": ["groups"] if (body.policy.scope or {}).get("groups") else [],
            "note": "Em modo monitorar nada seria bloqueado; os números mostram o que a política faria em modo aplicar."}
