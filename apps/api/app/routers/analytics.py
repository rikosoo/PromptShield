"""Números do painel: tudo calculado no banco, por tenant (RLS). Nada fixo no código."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from promptshield_detection.taxonomy import load as load_taxonomy
from sqlalchemy import text

from app.db import tenant_session
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1", tags=["painel"])
HIGH = 60


def window_start(days: int) -> datetime:
    """Início da janela: 00:00 UTC do primeiro dos `days` dias de calendário (hoje incluído).

    Totais, série diária, categorias, lista de prompts e simulação usam a MESMA janela, para os números fecharem."""
    first = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    return datetime(first.year, first.month, first.day, tzinfo=timezone.utc)


_since = window_start


@router.get("/taxonomy", summary="As 30 categorias (id, nome, grupo, risco padrão)")
def taxonomy(_: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> list[dict]:
    return [{"id": c.id, "nome": c.nome, "grupo": c.grupo, "risco_padrao": c.risco_padrao} for c in load_taxonomy().values()]


def compute_overview(s, since: datetime, until: datetime | None = None) -> dict:
    """Números do painel para [since, until). Usado também pelos relatórios, para os totais baterem com a tela."""
    if until is None:
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
    prm = {"hi": HIGH, "since": since, "until": until}
    row = s.execute(text("""
        SELECT count(*) AS events,
               count(*) FILTER (WHERE a.risk_score >= :hi) AS high_risk,
               count(*) FILTER (WHERE (a.flags::jsonb)->>'has_code' = 'true') AS with_code,
               count(*) FILTER (WHERE (a.flags::jsonb)->>'has_sensitive' = 'true') AS with_sensitive,
               count(*) FILTER (WHERE (a.flags::jsonb)->>'is_agent_action' = 'true') AS agent_actions,
               count(*) FILTER (WHERE a.decision = 'block') AS blocked,
               count(*) FILTER (WHERE a.would_decide = 'block' AND a.decision <> 'block') AS would_block,
               count(DISTINCT e.user_id) AS users
        FROM events e JOIN analyses a ON a.event_pk = e.id WHERE e.occurred_at >= :since AND e.occurred_at < :until"""), prm).mappings().one()
    daily = {r.d: (r.total, r.high) for r in s.execute(text("""
        SELECT (e.occurred_at AT TIME ZONE 'UTC')::date AS d, count(*) AS total,
               count(*) FILTER (WHERE a.risk_score >= :hi) AS high
        FROM events e JOIN analyses a ON a.event_pk = e.id WHERE e.occurred_at >= :since AND e.occurred_at < :until GROUP BY 1"""), prm)}
    by_dept = s.execute(text("""
        SELECT coalesce(e.department, '(sem departamento)') AS department, count(*) AS events,
               count(*) FILTER (WHERE a.risk_score >= :hi) AS high_risk
        FROM events e JOIN analyses a ON a.event_pk = e.id WHERE e.occurred_at >= :since AND e.occurred_at < :until
        GROUP BY 1 ORDER BY 3 DESC, 2 DESC, 1"""), prm).mappings().all()
    by_app = s.execute(text("""
        SELECT e.app, count(*) FILTER (WHERE NOT e.personal_account) AS corporate,
               count(*) FILTER (WHERE e.personal_account) AS personal
        FROM events e WHERE e.occurred_at >= :since AND e.occurred_at < :until GROUP BY 1 ORDER BY count(*) DESC, 1"""), prm).mappings().all()
    first = since.date()
    last = (until - timedelta(microseconds=1)).date()
    series = []
    d: date = first
    while d <= last:
        total, high = daily.get(d, (0, 0))
        series.append({"date": d.isoformat(), "events": total, "high_risk": high})
        d += timedelta(days=1)
    return {"high_risk_threshold": HIGH, "totals": dict(row), "daily": series,
            "by_department": [dict(r) for r in by_dept], "by_app": [dict(r) for r in by_app]}


@router.get("/stats/overview", summary="Indicadores, série diária de alto risco, departamentos e ferramentas")
def overview(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], days: int = Query(14, ge=1, le=90)) -> dict:
    with tenant_session(p.tenant_id) as s:
        out = compute_overview(s, _since(days))
    return {"days": days, **out}


@router.get("/stats/categories", summary="Quantos eventos por categoria (confiança de 0,5 ou mais)")
def category_counts(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], days: int = Query(14, ge=1, le=90)) -> dict[str, int]:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(text("""
            SELECT c->>'id' AS id, count(*) AS n
            FROM events e JOIN analyses a ON a.event_pk = e.id, jsonb_array_elements(a.categories::jsonb) c
            WHERE e.occurred_at >= :since GROUP BY 1"""), {"since": _since(days)})
        return {r.id: r.n for r in rows}


@router.get("/stats/signals", summary="Sinais para a análise: trechos sensíveis por tipo, o que as pessoas pedem, tipos de evento e ferramentas de agente")
def signals(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], days: int = Query(14, ge=1, le=90)) -> dict:
    """Só contagens (nunca texto). Um evento conta uma vez por tipo, mesmo com vários trechos do mesmo tipo."""
    since = {"since": _since(days)}
    with tenant_session(p.tenant_id) as s:
        spans = s.execute(text("""
            SELECT t AS k, count(*) AS n FROM (
              SELECT DISTINCT e.id, sp->>'type' AS t FROM events e JOIN analyses a ON a.event_pk = e.id,
                     jsonb_array_elements(a.spans::jsonb) sp WHERE e.occurred_at >= :since) x
            WHERE t IS NOT NULL AND t <> '' GROUP BY 1 ORDER BY 2 DESC"""), since)
        intents = s.execute(text("""
            SELECT i AS k, count(*) AS n FROM events e JOIN analyses a ON a.event_pk = e.id,
                   jsonb_array_elements_text(a.flags::jsonb->'intents') i
            WHERE e.occurred_at >= :since GROUP BY 1 ORDER BY 2 DESC"""), since)
        kinds = s.execute(text("SELECT kind AS k, count(*) AS n FROM events WHERE occurred_at >= :since GROUP BY 1 ORDER BY 2 DESC"), since)
        tools = s.execute(text("""SELECT tool_name AS k, count(*) AS n FROM events WHERE occurred_at >= :since AND tool_name IS NOT NULL
                                  GROUP BY 1 ORDER BY 2 DESC LIMIT 15"""), since)
        return {"span_types": {r.k: r.n for r in spans}, "intents": {r.k: r.n for r in intents},
                "kinds": {r.k: r.n for r in kinds}, "tools": {r.k: r.n for r in tools}}


@router.get("/stats/risk", summary="Indicador de risco por usuário e departamento, com evolução diária")
def risk_stats(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], days: int = Query(14, ge=1, le=90)) -> dict:
    from app.reports import user_risk

    start = _since(days).date()
    with tenant_session(p.tenant_id) as s:
        return user_risk(s, start, datetime.now(timezone.utc).date(), top=50)


@router.get("/people", summary="Pessoas que usaram IA: volume, risco e última atividade (para filtrar prompts por pessoa)")
def people(
    p: Annotated[Principal, Depends(require_roles(*READ_ROLES))],
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="parte do nome/e-mail")] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    like = None if not q else "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(text("""
            SELECT e.user_id, max(e.department) AS department, count(*) AS events,
                   count(*) FILTER (WHERE a.risk_score >= :hi) AS high_risk,
                   max(a.risk_score) AS max_risk, round(avg(a.risk_score))::int AS avg_risk,
                   max(e.occurred_at) AS last_seen
            FROM events e JOIN analyses a ON a.event_pk = e.id
            WHERE e.occurred_at >= :since AND (CAST(:like AS text) IS NULL OR e.user_id ILIKE CAST(:like AS text) ESCAPE '\\')
            GROUP BY e.user_id ORDER BY 4 DESC, 3 DESC, 1 LIMIT :lim"""),
            {"hi": HIGH, "since": window_start(days), "like": like, "lim": limit}).mappings().all()
    return [{**r, "last_seen": r["last_seen"].isoformat()} for r in rows]
