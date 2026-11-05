"""Score 0-100 explicável e versionado. Mesmo evento, mesmo score e mesmos motivos."""
from __future__ import annotations

from .models import Finding, Reason
from .taxonomy import Category

SCORE_VERSION = "2026-11-a"   # 2026-11-a: infraestrutura no texto (IP, host interno, caminho com usuário, arquivo de negócio)
THRESHOLD = 0.5  # confiança mínima para a categoria contar
SECONDARY_FACTOR = 0.3
AGENT_ACTION_BONUS = 10
PERSONAL_ACCOUNT_BONUS = 10


def score(best: dict[str, Finding], cats: dict[str, Category], is_agent_action: bool,
          personal_account: bool) -> tuple[int, list[Reason]]:
    contribs: list[tuple[float, str, str]] = []
    for cid, f in best.items():
        if f.confidence < THRESHOLD:
            continue
        contribs.append((cats[cid].weight * f.confidence, cid, f.rule))
    contribs.sort(key=lambda x: (-x[0], x[1]))
    reasons: list[Reason] = []
    total = 0.0
    for i, (value, cid, rule) in enumerate(contribs):
        part = value if i == 0 else value * SECONDARY_FACTOR
        total += part
        reasons.append(Reason(rule=rule, contribution=round(part), category=cid))
    if total > 0 and is_agent_action:
        total += AGENT_ACTION_BONUS
        reasons.append(Reason("Ação de agente (contexto)", AGENT_ACTION_BONUS))
    if total > 0 and personal_account:
        total += PERSONAL_ACCOUNT_BONUS
        reasons.append(Reason("Conta pessoal (contexto)", PERSONAL_ACCOUNT_BONUS))
    return min(100, round(total)), reasons
