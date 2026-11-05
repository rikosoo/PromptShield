"""Métricas do piloto (30 dias, só monitorar): cobertura de usuários, taxa de falso positivo revisada por amostragem, tempo até o
primeiro alerta. Tudo vem do banco; nada fixo no código.

Honestidade estatística:
- A taxa de falso positivo vem de uma amostra ALEATÓRIA dos eventos que o produto SINALIZOU (score >= corte). Mede quantos dos
  sinalizados estavam errados (o complemento é a precisão). NÃO mede falsos negativos (o que passou sem ser sinalizado).
- Com poucas revisões a taxa é instável: devolvemos o intervalo de confiança de Wilson (95%) e um aviso abaixo de MIN_REVIEWS.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Tenant

MIN_REVIEWS = 30
Z95 = 1.959963984540054
LABELS = ("verdadeiro_positivo", "falso_positivo", "incerto")


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Intervalo de Wilson para uma proporção. None sem observações."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def summary(s: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    t = s.get(Tenant, tenant_id)
    assert t is not None
    start = t.pilot_started_at
    since = start or datetime(1970, 1, 1, tzinfo=timezone.utc)
    prm = {"since": since, "now": now}

    users = s.execute(text("SELECT count(DISTINCT user_id) FROM events WHERE received_at >= :since"), prm).scalar_one()
    by_dept = [dict(r) for r in s.execute(text("""SELECT coalesce(department, '(sem departamento)') AS department, count(DISTINCT user_id) AS users
                                                  FROM events WHERE received_at >= :since GROUP BY 1 ORDER BY 2 DESC, 1"""), prm).mappings()]
    by_channel = [dict(r) for r in s.execute(text("""SELECT channel, app, count(DISTINCT user_id) AS users, count(*) AS events
                                                     FROM events WHERE received_at >= :since GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2"""), prm).mappings()]
    expected = t.pilot_expected_users
    coverage = {"active_users": users, "expected_users": expected,
                "rate": round(users / expected, 4) if expected else None, "by_department": by_dept, "by_channel": by_channel}

    totals = dict(s.execute(text("""SELECT count(*) AS events, count(*) FILTER (WHERE a.risk_score >= 60) AS high_risk,
                                    count(*) FILTER (WHERE a.decision <> 'allow') AS enforced_decisions,
                                    count(*) FILTER (WHERE a.would_decide <> 'allow') AS would_act
                                    FROM events e JOIN analyses a ON a.event_pk = e.id WHERE e.received_at >= :since"""), prm).mappings().one())
    first_event = s.execute(text("SELECT min(received_at) FROM events WHERE received_at >= :since"), prm).scalar()
    first_alert = s.execute(text("SELECT min(first_seen) FROM alerts WHERE first_seen >= :since"), prm).scalar()
    first_incident = s.execute(text("""SELECT min(i.created_at) FROM incidents i WHERE i.created_at >= :since"""), prm).scalar()
    origin = start or first_event
    ttfa = (first_alert - origin).total_seconds() if first_alert and origin and first_alert >= origin else None

    reviews = dict(s.execute(text("""SELECT count(*) FILTER (WHERE label IS NOT NULL) AS reviewed, count(*) FILTER (WHERE label IS NULL) AS pending,
                                     count(*) FILTER (WHERE label = 'falso_positivo') AS false_positive,
                                     count(*) FILTER (WHERE label = 'verdadeiro_positivo') AS true_positive,
                                     count(*) FILTER (WHERE label = 'incerto') AS unsure FROM pilot_reviews"""), prm).mappings().one())
    decided = reviews["false_positive"] + reviews["true_positive"]            # "incerto" não entra na taxa
    ci = wilson(reviews["false_positive"], decided)
    fp = {"reviewed": reviews["reviewed"], "pending": reviews["pending"], "false_positive": reviews["false_positive"],
          "true_positive": reviews["true_positive"], "unsure": reviews["unsure"], "decided": decided,
          "rate": round(reviews["false_positive"] / decided, 4) if decided else None,
          "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
          "small_sample": decided < MIN_REVIEWS, "min_reviews": MIN_REVIEWS,
          "scope": "só eventos que o produto sinalizou; não mede falsos negativos (o que passou sem ser sinalizado)"}

    policies = [dict(r) for r in s.execute(text("SELECT mode, count(*) AS n FROM policies WHERE enabled GROUP BY 1")).mappings()]
    day = (now - start).days + 1 if start else None
    return {"started_at": start.isoformat() if start else None, "pilot_days": t.pilot_days, "day": day,
            "ends_at": (start + timedelta(days=t.pilot_days)).isoformat() if start else None,
            "days_remaining": max(0, t.pilot_days - day) if day else None,
            "coverage": coverage, "totals": totals, "false_positive": fp,
            "time_to_first_alert_seconds": ttfa, "first_alert_at": first_alert.isoformat() if first_alert else None,
            "first_incident_at": first_incident.isoformat() if first_incident else None,
            "policies_by_mode": policies, "monitor_only": totals["enforced_decisions"] == 0 and all(p["mode"] == "monitor" for p in policies)}
