"""Pacotes de regras no servidor do cliente: guardar (validado), carregar para o motor (assinatura reconferida), mudar de fase e contar ocorrências.

Ciclo: recebido -> `staged` (guardado, SEM efeito) -> `shadow` (registra o que casaria, SEM efeito) -> `active` (vale). Só o administrador muda de fase (auditado) e só um
pacote fica em `shadow`/`active` por vez. `retired` volta ao comportamento de fábrica. O pacote é dado: não executa código (promptshield_detection.rulepack)."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from promptshield_detection import rulepack as rp
from promptshield_licensing import ReleaseError, verify_rulepack
from sqlalchemy import select, text

from app.db import anonymous_session
from app.models import RulePackHit, RulePackRow

log = logging.getLogger("promptshield.rulepacks")
CACHE_SECONDS = 15.0
ALLOWED = {("staged", "shadow"), ("shadow", "active"), ("shadow", "retired"), ("active", "retired"), ("staged", "retired"), ("retired", "shadow")}


class PackStateError(Exception):
    pass


@dataclass(frozen=True)
class Live:
    pack_id: uuid.UUID
    version: str
    mode: str                      # shadow | active
    pack: rp.RulePack

    @property
    def weights(self) -> dict[str, int]:
        return dict(self.pack.weights) if self.mode == "active" else {}      # em sombra NADA muda, nem os pesos


_cache: tuple[float, Live | None] | None = None
_lock = threading.Lock()


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def _pinned():
    from app import license_client

    return license_client._pinned()


def _load_live() -> Live | None:
    with anonymous_session() as s:
        row = s.execute(select(RulePackRow).where(RulePackRow.status.in_(("shadow", "active")))).scalar()
        if row is None:
            return None
        s.expunge(row)
    try:
        payload = verify_rulepack(row.token, _pinned())              # reconfere a assinatura A CADA CARGA: um banco adulterado não injeta regras
        return Live(row.id, row.version, row.status, rp.load(payload))
    except Exception as exc:  # noqa: BLE001 - qualquer problema = sem pacote (o motor de fábrica segue valendo) e um aviso no log
        log.warning("pacote de regras %s ignorado: %s", row.version, type(exc).__name__)
        return None


def current() -> Live | None:
    """Pacote em vigor (sombra ou ativo) com cache curto. Nunca levanta: sem pacote, o motor de fábrica segue como sempre."""
    global _cache
    with _lock:
        if _cache and time.monotonic() < _cache[0]:
            return _cache[1]
    live = _load_live()
    with _lock:
        _cache = (time.monotonic() + CACHE_SECONDS, live)
    return live


def record_hits(session, live: Live, info: dict[str, Any] | None) -> None:
    """Conta quantas vezes cada regra casou (para o administrador decidir se promove o pacote). Só ids e contagens: nenhum conteúdo."""
    if not info or not info.get("hits"):
        return
    for rid in info["hits"]:
        session.execute(text("""INSERT INTO rule_pack_hits (pack_id, rule_id, mode, hits) VALUES (:p, :r, :m, 1)
                                ON CONFLICT (pack_id, rule_id, mode) DO UPDATE SET hits = rule_pack_hits.hits + 1, last_at = now()"""),
                        {"p": live.pack_id, "r": str(rid)[:64], "m": live.mode})


# ---------------------------------------------------------------- guardar um pacote recebido
def stage(token: str, version: str, now: datetime) -> uuid.UUID | None:
    """Confere assinatura, valida (inclui o teste de tempo das expressões regulares) e guarda como `staged`. Devolve o id; None se a versão já existe.
    Levanta ReleaseError ou PackError com o motivo (o chamador mostra ao administrador e avisa o fornecedor)."""
    payload = verify_rulepack(token, _pinned())
    if payload.get("version") != version:
        raise ReleaseError("a versão dentro do pacote não é a do aviso")
    pack = rp.load(payload, check_budget=True)
    summary = pack.summary()
    summary["rules_list"] = [{"id": r.id, "category": r.category, "confidence": r.confidence, "rule": r.rule, "kind": r.kind, "masks": bool(r.masked)} for r in pack.rules]
    from hashlib import sha256
    with anonymous_session() as s:
        if s.execute(select(RulePackRow.id).where(RulePackRow.version == version)).scalar() is not None:
            return None
        row = RulePackRow(version=version, sha256=sha256(token.encode()).hexdigest(), token=token, notes=pack.notes, summary=summary, status="staged", received_at=now)
        s.add(row)
        s.flush()
        return row.id


# ---------------------------------------------------------------- mudar de fase (só o administrador; a API audita)
def transition(pack_id: uuid.UUID, to: str, actor: str, now: datetime | None = None) -> RulePackRow:
    now = now or datetime.now(timezone.utc)
    with anonymous_session() as s:
        row = s.execute(select(RulePackRow).where(RulePackRow.id == pack_id).with_for_update()).scalar()
        if row is None:
            raise PackStateError("pacote não encontrado")
        if (row.status, to) not in ALLOWED:
            raise PackStateError(f"não dá para ir de «{row.status}» para «{to}»")
        if to == "shadow":
            s.execute(text("UPDATE rule_packs SET status = 'retired', retired_at = :n WHERE status IN ('shadow','active') AND id <> :i"), {"n": now, "i": pack_id})
            row.status, row.activated_by, row.activated_at, row.retired_at = "shadow", actor, now, None
        elif to == "active":
            row.status, row.promoted_at, row.activated_by = "active", now, actor
        else:
            row.status, row.retired_at = "retired", now
        s.flush()
        s.expunge(row)
    invalidate()
    return row


def listing(limit: int = 30) -> list[dict[str, Any]]:
    with anonymous_session() as s:
        rows = s.execute(select(RulePackRow).order_by(RulePackRow.received_at.desc()).limit(limit)).scalars().all()
        hits = {r.id: 0 for r in rows}
        for pid, n in s.execute(text("SELECT pack_id, sum(hits) FROM rule_pack_hits GROUP BY pack_id")).all():
            if pid in hits:
                hits[pid] = int(n)
        return [{"id": str(r.id), "version": r.version, "status": r.status, "notes": r.notes, "received_at": r.received_at.isoformat(), "activated_by": r.activated_by,
                 "activated_at": r.activated_at.isoformat() if r.activated_at else None, "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
                 "rules": r.summary.get("rules", 0), "weights": r.summary.get("weights", {}), "hits": hits[r.id]} for r in rows]


def detail(pack_id: uuid.UUID) -> dict[str, Any] | None:
    with anonymous_session() as s:
        row = s.get(RulePackRow, pack_id)
        if row is None:
            return None
        hits = {(h.rule_id, h.mode): h for h in s.execute(select(RulePackHit).where(RulePackHit.pack_id == pack_id)).scalars()}
        rules = []
        for r in row.summary.get("rules_list", []):
            sh, ac = hits.get((r["id"], "shadow")), hits.get((r["id"], "active"))
            rules.append({**r, "hits_shadow": int(sh.hits) if sh else 0, "hits_active": int(ac.hits) if ac else 0,
                          "last_hit": max([h.last_at for h in (sh, ac) if h], default=None)})
        for r in rules:
            r["last_hit"] = r["last_hit"].isoformat() if r["last_hit"] else None
        return {"id": str(row.id), "version": row.version, "status": row.status, "notes": row.notes, "received_at": row.received_at.isoformat(),
                "weights": row.summary.get("weights", {}), "by_category": row.summary.get("by_category", {}), "rules": rules}


def installed_version() -> str | None:
    """Maior versão de regras já RECEBIDA (qualquer fase): um aviso só vale se for maior que ela."""
    from promptshield_licensing import parse_version

    with anonymous_session() as s:
        versions = list(s.execute(select(RulePackRow.version)).scalars())
    return max(versions, key=parse_version, default=None)


def live_version() -> str | None:
    with anonymous_session() as s:
        return s.execute(select(RulePackRow.version).where(RulePackRow.status.in_(("shadow", "active")))).scalar()
