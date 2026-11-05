"""Indicador de risco por usuário e por departamento: agregação do histórico, com fórmula explícita e versionada.

É um INDICADOR para priorizar revisão humana. Nunca é prova de má conduta.

Fórmula (USER_SCORE_VERSION):
  score = min(100, maior_score_de_um_evento + bônus_de_repetição)
  bônus_de_repetição = min(20, 5 x (eventos com score >= 35 no período - 1))
O departamento é a média dos scores dos seus usuários com atividade (e mostra quantos estão em risco alto).
O mesmo cálculo, aplicado a um dia só, forma a série de evolução.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

USER_SCORE_VERSION = "2026-10-a"
MEDIUM = 35
HIGH = 60
REPEAT_STEP = 5
REPEAT_CAP = 20
DISCLAIMER = "Indicador de risco, requer revisão humana. Não é prova de má conduta."


@dataclass
class DayAgg:
    events: int
    max_score: int
    n_medium: int  # eventos com score >= MEDIUM
    n_high: int  # eventos com score >= HIGH


@dataclass
class Score:
    score: int
    reasons: list[dict] = field(default_factory=list)


def entity_score(max_score: int, n_medium: int) -> Score:
    if max_score <= 0:
        return Score(0, [])
    reasons = [{"rule": "Maior risco de um evento no período", "contribution": max_score}]
    bonus = min(REPEAT_CAP, REPEAT_STEP * max(0, n_medium - 1))
    if bonus:
        reasons.append({"rule": f"Repetição: {n_medium} eventos com risco de {MEDIUM} ou mais", "contribution": bonus})
    return Score(min(100, max_score + bonus), reasons)


def aggregate(days: list[date], rows: list[tuple[str, str | None, date, DayAgg]], top: int = 50) -> dict:
    """rows: (usuário, departamento, dia, agregado do dia). Devolve usuários, departamentos e séries diárias."""
    per_user: dict[str, dict[date, DayAgg]] = defaultdict(dict)
    dept_of: dict[str, str | None] = {}
    for user, dept, day, agg in rows:
        per_user[user][day] = agg
        dept_of[user] = dept

    users: list[dict] = []
    daily_user: dict[str, list[int]] = {}
    for user, by_day in per_user.items():
        total = entity_score(max(a.max_score for a in by_day.values()), sum(a.n_medium for a in by_day.values()))
        series = [entity_score(by_day[d].max_score, by_day[d].n_medium).score if d in by_day else 0 for d in days]
        daily_user[user] = series
        users.append({"user_id": user, "department": dept_of[user], "score": total.score, "reasons": total.reasons,
                      "events": sum(a.events for a in by_day.values()), "high_events": sum(a.n_high for a in by_day.values()),
                      "series": series})
    users.sort(key=lambda u: (-u["score"], -u["high_events"], u["user_id"]))

    by_dept: dict[str, list[dict]] = defaultdict(list)
    for u in users:
        by_dept[u["department"] or "(sem departamento)"].append(u)
    depts = []
    for name, members in by_dept.items():
        series = []
        for i in range(len(days)):
            active = [m["series"][i] for m in members if m["series"][i] > 0]
            series.append(round(sum(active) / len(active)) if active else 0)
        depts.append({"department": name, "score": round(sum(m["score"] for m in members) / len(members)), "users": len(members),
                      "users_high": sum(1 for m in members if m["score"] >= HIGH),
                      "events": sum(m["events"] for m in members), "series": series})
    depts.sort(key=lambda d: (-d["score"], d["department"]))
    return {"score_version": USER_SCORE_VERSION, "disclaimer": DISCLAIMER, "days": [d.isoformat() for d in days],
            "users": users[:top], "departments": depts}
