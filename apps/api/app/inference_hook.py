"""Inference hooks do Claude Enterprise: processa um frame verificado e devolve o veredito (docs/inference-hooks.md).

Sem conteúdo em log nem na tabela de requisições. O texto passa pelo motor e só a versão mascarada é gravada.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from promptshield_detection.taxonomy import load as load_taxonomy
from promptshield_inference_hooks import Block, Frame, allow, deny
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto, metrics
from app.config import settings
from app.models import Analysis, Event, InferenceHookConfig, InferenceHookRequest, Tenant
from app.schemas import Actor, Content, Context, EventIn, Source
from app.security import Principal
from app.services import ingest

log = logging.getLogger("promptshield.inference_hook")
NAMESPACE = uuid.UUID("5d0c3a52-6a53-4b2e-9f0e-3f6f0a1c7a11")  # ids determinísticos dos eventos (idempotência)
DENY_DECISIONS = ("block", "mask", "ask_justification")  # o hook só entende allow/deny: mask e ask viram deny (sem reescrita)


class BudgetExceeded(Exception):
    pass


@dataclass
class Outcome:
    verdict: dict[str, Any]
    outcome: str
    would_deny: bool = False
    blocks_total: int = 0
    blocks_new: int = 0
    categories: list[str] = field(default_factory=list)
    error: str | None = None
    deny_reasons: list[str] = field(default_factory=list)


def app_id(application: str) -> str:
    """`claude-ai` -> `claude_ai` (ids de ferramenta do restante do produto usam sublinhado)."""
    return re.sub(r"[^a-z0-9_]+", "_", application.lower()).strip("_")[:80] or "desconhecido"


def event_id_for(tenant_id: uuid.UUID, frame: Frame, block: Block) -> uuid.UUID:
    who = frame.actor_id or frame.actor_email or ""
    return uuid.uuid5(NAMESPACE, f"{tenant_id}|{who}|{frame.session_id or ''}|{block.fingerprint}")


def deniable(frame: Frame, block: Block) -> bool:
    """O que pode derrubar o pedido. No frame `prompt`, só conteúdo de origem do usuário (texto, anexo, resultado de ferramenta).
    Respostas e chamadas de ferramenta antigas do assistente já aconteceram: são só registradas. No frame `tool_call`, só chamadas."""
    return block.kind == "tool_call" if frame.type == "tool_call" else block.role == "user"


def select_blocks(frame: Frame, scope: str) -> list[Block]:
    if frame.type == "tool_call" or scope == "full":
        return frame.blocks
    last_user = max((b.msg_index for b in frame.blocks if b.role == "user"), default=None)
    return [b for b in frame.blocks if b.msg_index == last_user] if last_user is not None else []


def _to_event(tenant_id: uuid.UUID, frame: Frame, block: Block) -> EventIn:
    text = block.text
    if text is not None and len(text) > settings.max_text_chars:
        text = text[: settings.max_text_chars]
    return EventIn(
        event_id=event_id_for(tenant_id, frame, block), occurred_at=datetime.now(timezone.utc),
        source=Source(channel="inference_hook", app=app_id(frame.application), integration_status="partial"),
        actor=Actor(user_id=(frame.actor_email or frame.actor_id or "desconhecido")[:200], agent_id=None),
        kind=block.kind,  # type: ignore[arg-type]
        content=Content(text=text, tool_name=(block.tool_name or None), tool_input=block.tool_input),
        context=Context(session_id=(frame.session_id or None), personal_account=False))


def deny_message(category_ids: list[str], frame_type: str, policy_url: str | None) -> str:
    tax = load_taxonomy()
    names = [tax[c].nome if c in tax else c for c in dict.fromkeys(category_ids)][:3]
    what = ", ".join(names) if names else "conteúdo que a política da empresa não permite"
    subject = "a ação pedida ao assistente" if frame_type == "tool_call" else "uma mensagem desta conversa"
    msg = f"O PromptShield bloqueou {subject}: {what}. Edite ou remova esse conteúdo e envie de novo."
    if policy_url:
        msg += f" Política de uso de IA: {policy_url}"
    return msg


def evaluate(session: Session, p: Principal, tenant: Tenant, cfg: InferenceHookConfig, frame: Frame, deadline: float) -> Outcome:
    blocks = select_blocks(frame, cfg.scope)
    shadow = cfg.mode == "shadow"
    ids = {b.fingerprint: event_id_for(p.tenant_id, frame, b) for b in blocks}
    seen = {r.event_id: r for r in session.execute(
        select(Event.event_id, Analysis.decision, Analysis.would_decide, Analysis.categories)
        .join(Analysis, Analysis.event_pk == Event.id).where(Event.event_id.in_(list(ids.values())))).all()}
    out = Outcome(allow(), "allow", blocks_total=len(blocks))
    offending: list[str] = []
    top: list[str] = []
    for b in blocks:
        eid = ids[b.fingerprint]
        row = seen.get(eid)
        if row is None:
            if time.monotonic() > deadline:
                raise BudgetExceeded
            res = ingest(session, p, _to_event(p.tenant_id, frame, b), force_monitor=shadow or not deniable(frame, b))
            decision, would, cats = res.decision, res.would_decide, [c["id"] for c in res.categories]
            out.blocks_new += 1
        else:
            decision, would, cats = row.decision, row.would_decide, [c["id"] for c in row.categories]
        if not deniable(frame, b):
            continue
        if would in DENY_DECISIONS:
            out.would_deny = True
        if decision in DENY_DECISIONS:
            offending.extend(cats[:2])
        top.extend(cats[:1])
    out.categories = list(dict.fromkeys(top))[:5]
    if offending and not shadow:
        out.outcome = "deny"
        out.deny_reasons = offending
    elif shadow:
        out.outcome = "shadow_allow" if out.would_deny else "allow"
    return out


def decrypt_secrets(cfg: InferenceHookConfig, now: datetime) -> list[str]:
    secrets: list[str] = []
    if cfg.secret_ciphertext:
        secrets.append(crypto.decrypt_secret(cfg.tenant_id, cfg.secret_ciphertext))
    if cfg.previous_secret_ciphertext and cfg.previous_expires_at and cfg.previous_expires_at > now:
        secrets.append(crypto.decrypt_secret(cfg.tenant_id, cfg.previous_secret_ciphertext))
    return secrets


def failure_verdict(tenant: Tenant, cfg: InferenceHookConfig) -> tuple[dict[str, Any], str]:
    """Falha NOSSA (erro interno ou orçamento de tempo): sombra sempre permite; senão segue o `failure_mode` do tenant."""
    if cfg.mode == "shadow" or tenant.failure_mode == "open":
        return allow(), "failure_allow"
    return deny("O PromptShield não conseguiu verificar esta mensagem agora. Tente novamente em instantes ou fale com o administrador."), "failure_deny"


def record(session: Session, p: Principal, frame: Frame, request_id: str, o: Outcome, started: float, reference_id: str | None) -> None:
    from sqlalchemy.dialects.postgresql import insert

    session.execute(insert(InferenceHookRequest).values(
        tenant_id=p.tenant_id, request_id=request_id[:200], frame_type=(frame.type or "desconhecido")[:40],
        application=app_id(frame.application), outcome=o.outcome, would_deny=o.would_deny, blocks_total=o.blocks_total,
        blocks_new=o.blocks_new, skipped_attachments=frame.skipped_attachments, categories=o.categories, reference_id=reference_id,
        latency_ms=int((time.monotonic() - started) * 1000), error=o.error)
        .on_conflict_do_nothing(index_elements=["tenant_id", "request_id"]))


def process(session: Session, p: Principal, cfg: InferenceHookConfig, frame: Frame, request_id: str, started: float) -> dict[str, Any]:
    """Devolve o veredito (dict pronto para JSON). Nunca levanta: falhas viram o veredito de falha configurado."""
    tenant = session.get(Tenant, p.tenant_id)
    assert tenant is not None
    now = datetime.now(timezone.utc)
    cfg.last_request_at = now
    if not frame.known:
        o = Outcome(allow(), "unknown_type")
    elif frame.is_config_test:
        cfg.last_test_at = now
        o = Outcome(allow(), "config_test")
    elif frame.type == "tool_call" and not cfg.evaluate_tool_calls:
        o = Outcome(allow(), "allow")
    else:
        deadline = started + settings.inference_hook_budget_ms / 1000
        try:
            with session.begin_nested():
                o = evaluate(session, p, tenant, cfg, frame, deadline)
        except BudgetExceeded:
            verdict, outcome = failure_verdict(tenant, cfg)
            o = Outcome(verdict, outcome, error="orçamento de tempo estourado")
        except Exception as exc:  # noqa: BLE001 - o veredito de falha configurado decide; só o TIPO vai para o log (nada de conteúdo)
            log.error("falha ao avaliar frame (%s)", type(exc).__name__)
            verdict, outcome = failure_verdict(tenant, cfg)
            o = Outcome(verdict, outcome, error=f"erro interno ({type(exc).__name__})"[:200])
    ref = f"ps:{uuid.uuid4().hex[:32]}" if o.outcome in ("deny", "failure_deny") else None
    if o.outcome == "deny":
        o.verdict = deny(deny_message(o.deny_reasons, frame.type, tenant.policy_url), ref)
    elif o.outcome == "failure_deny":
        o.verdict = deny(o.verdict["deny_reason"], ref)
    record(session, p, frame, request_id, o, started, ref)
    metrics.inc("ps_inference_hook_total", outcome=o.outcome)
    return o.verdict
