"""Policy engine puro (sem banco): escopo + condição -> ação. Testável isoladamente.

Regras:
- Política com `scope` vazio vale para todos; cada chave presente (departments, apps, groups) restringe.
- `match.categories` vazio vale para qualquer categoria; `min_confidence` (padrão 0,5) e `min_score` (padrão 0).
- Em modo `monitor` a decisão devolvida é sempre `allow`; a decisão que teria sido tomada vai em `would_decide`.
- Entre políticas que casam, vence a ação mais forte: block > ask_justification > mask > alert > allow.
- Exceção (pessoa ou grupo, com validade): a política que casaria é registrada em `hits` com `excepted="true"` e NÃO conta para a decisão.
  Exceção por grupo usa só `Subject.member_groups` (membros cadastrados no servidor), nunca `Subject.groups` (declarados pelo sensor no
  evento): senão qualquer coletor poderia se declarar de um grupo isento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

RANK = {"allow": 0, "alert": 1, "mask": 2, "ask_justification": 3, "block": 4}


@dataclass(frozen=True)
class PolicySpec:
    id: str
    name: str
    action: str
    mode: str
    enabled: bool = True
    scope: dict[str, Any] = field(default_factory=dict)
    match: dict[str, Any] = field(default_factory=dict)
    exceptions: tuple[dict[str, Any], ...] = ()   # {"user_id": str | None, "group": str | None, "expires_at": datetime}


@dataclass(frozen=True)
class Subject:
    department: str | None = None
    app: str | None = None
    groups: tuple[str, ...] = ()          # declarados no evento: valem para ESCOPO, nunca para exceção
    user_id: str | None = None
    member_groups: tuple[str, ...] = ()   # cadastrados no servidor: valem para exceção


@dataclass
class Evaluation:
    decision: str = "allow"
    would_decide: str = "allow"
    hits: list[dict[str, str]] = field(default_factory=list)


def _in_scope(p: PolicySpec, s: Subject) -> bool:
    sc = p.scope or {}
    if sc.get("departments") and (s.department or "") not in sc["departments"]:
        return False
    if sc.get("apps") and (s.app or "") not in sc["apps"]:
        return False
    return not (sc.get("groups") and not set(sc["groups"]) & (set(s.groups) | set(s.member_groups)))


def _matches(p: PolicySpec, categories: list[dict[str, Any]], score: int) -> bool:
    m = p.match or {}
    if score < m.get("min_score", 0):
        return False
    wanted = set(m.get("categories") or [])
    floor = m.get("min_confidence", 0.5)
    hit = {c["id"] for c in categories if c["confidence"] >= floor}
    if wanted:
        return bool(wanted & hit)
    return bool(hit) or m.get("min_score", 0) > 0


def _excepted(p: PolicySpec, s: Subject, now: datetime) -> bool:
    for x in p.exceptions:
        if x["expires_at"] <= now:
            continue
        if (x.get("user_id") and x["user_id"] == s.user_id) or (x.get("group") and x["group"] in s.member_groups):
            return True
    return False


def evaluate(policies: list[PolicySpec], subject: Subject, categories: list[dict[str, Any]], score: int,
             now: datetime | None = None) -> Evaluation:
    ev = Evaluation()
    now = now or datetime.now(timezone.utc)
    for p in policies:
        if not p.enabled or not _in_scope(p, subject) or not _matches(p, categories, score):
            continue
        if _excepted(p, subject, now):
            ev.hits.append({"policy_id": p.id, "name": p.name, "action": p.action, "mode": p.mode, "excepted": "true"})
            continue
        ev.hits.append({"policy_id": p.id, "name": p.name, "action": p.action, "mode": p.mode})
        if RANK[p.action] > RANK[ev.would_decide]:
            ev.would_decide = p.action
        if p.mode == "enforce" and RANK[p.action] > RANK[ev.decision]:
            ev.decision = p.action
    return ev


DEFAULT_POLICIES: list[dict[str, Any]] = [
    {"name": "Bloquear segredos e chaves", "action": "block", "match": {"categories": ["segredo"]}},
    {"name": "Mascarar CPF, CNPJ e contato", "action": "mask", "match": {"categories": ["pii"]}},
    {"name": "Mascarar cartões", "action": "mask", "match": {"categories": ["financeiro"]}},
    {"name": "Alertar injection e jailbreak", "action": "alert",
     "match": {"categories": ["injection_direta", "injection_indireta", "jailbreak", "extracao_system_prompt"]}},
    {"name": "Bloquear comandos destrutivos de agente", "action": "block",
     "match": {"categories": ["shell_destrutivo", "alteracao_permissao"]}},
    {"name": "Bloquear leitura de .env e credenciais", "action": "block", "match": {"categories": ["leitura_env"]}},
    {"name": "Alertar rede externa", "action": "alert", "match": {"categories": ["rede_externa"]}},
    {"name": "Bloquear exfiltração", "action": "block", "match": {"categories": ["exfiltracao_ferramenta", "envenenamento_mcp"]}},
]
