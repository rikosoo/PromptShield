"""Alertas (lista) e canais de notificação (administração). Segredos de canais nunca voltam nas respostas."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app import alerts as alert_rules
from app import audit, crypto, notifier
from app.db import tenant_session
from app.models import Alert, NotificationChannel, OutboxItem, Tenant
from app.schemas import ChannelIn, ChannelPatch
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1", tags=["alertas"])
ADMIN = ("admin",)


def _alert_view(a: Alert) -> dict:
    return {"id": str(a.id), "rule": a.rule, "rule_label": alert_rules.RULE_LABELS.get(a.rule, a.rule), "severity": a.severity,
            "title": a.title, "user_id": a.user_id, "department": a.department, "count": a.count,
            "first_seen": a.first_seen.isoformat(), "last_seen": a.last_seen.isoformat(),
            "incident_id": str(a.incident_id) if a.incident_id else None, "score": (a.detail or {}).get("score"),
            "categories": (a.detail or {}).get("categories", [])}


@router.get("/alerts", summary="Alertas (deduplicados: um por regra, usuário, categoria e janela)")
def list_alerts(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))], rule: str | None = None,
                limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        q = select(Alert).order_by(Alert.last_seen.desc()).limit(limit)
        if rule:
            q = q.where(Alert.rule == rule)
        return [_alert_view(a) for a in s.execute(q).scalars()]


def _channel_view(ch: NotificationChannel, stats: dict[str, int] | None = None) -> dict:
    cfg = ch.config or {}
    shown = ch.target
    if ch.kind in ("webhook", "slack", "teams", "siem_webhook"):  # a URL é um segredo (Slack/Teams): mostra só o host
        from urllib.parse import urlsplit

        shown = f"{urlsplit(ch.target).scheme}://{urlsplit(ch.target).hostname}/…"
    return {"id": str(ch.id), "kind": ch.kind, "name": ch.name, "target": shown, "enabled": ch.enabled,
            "integration_status": notifier.STATUS[ch.kind], "min_severity": cfg.get("min_severity"),
            "min_score": cfg.get("min_score"), "proto": cfg.get("proto"), "has_secret": ch.secret_ciphertext is not None,
            "outbox": stats or {}}


@router.get("/channels", summary="Canais de notificação e SIEM")
def list_channels(p: Annotated[Principal, Depends(require_roles(*ADMIN))]) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        stats: dict[uuid.UUID, dict[str, int]] = {}
        for cid, st, n in s.execute(select(OutboxItem.channel_id, OutboxItem.status, func.count()).group_by(OutboxItem.channel_id, OutboxItem.status)):
            stats.setdefault(cid, {})[st] = n
        return [_channel_view(c, stats.get(c.id)) for c in s.execute(select(NotificationChannel).order_by(NotificationChannel.created_at)).scalars()]


@router.post("/channels", status_code=201, summary="Cria um canal (valida o destino; URLs precisam ser https e públicas)")
def create_channel(body: ChannelIn, p: Annotated[Principal, Depends(require_roles(*ADMIN))]) -> dict:
    try:
        notifier.validate_target(body.kind, body.target)
    except notifier.DeliveryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    cfg = {k: v for k, v in (("min_severity", body.min_severity), ("min_score", body.min_score), ("proto", body.proto)) if v is not None}
    secret = None
    target_blob = None
    shown = body.target
    if body.kind in ("webhook", "slack", "teams", "siem_webhook"):  # a URL é um segredo (Slack/Teams): cifrada, e só o host fica visível
        from urllib.parse import urlsplit

        parts = urlsplit(body.target)
        shown = f"{parts.scheme}://{parts.hostname}/…"
        try:
            target_blob = crypto.encrypt_secret(p.tenant_id, body.target)
        except crypto.MasterKeyMissingError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "chave mestra não configurada: não dá para guardar a URL do canal") from exc
    if body.secret:
        try:
            secret = crypto.encrypt_secret(p.tenant_id, body.secret)
        except crypto.MasterKeyMissingError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "chave mestra não configurada: não dá para guardar o segredo") from exc
    with tenant_session(p.tenant_id) as s:
        ch = NotificationChannel(tenant_id=p.tenant_id, kind=body.kind, name=body.name, target=shown, config=cfg,
                                 secret_ciphertext=secret, target_ciphertext=target_blob, enabled=body.enabled)
        s.add(ch)
        s.flush()
        audit.write(s, p, "channel.create", "channel", str(ch.id), {"kind": body.kind, "name": body.name})
        return _channel_view(ch)


@router.patch("/channels/{channel_id}")
def patch_channel(channel_id: uuid.UUID, body: ChannelPatch, p: Annotated[Principal, Depends(require_roles(*ADMIN))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        ch = s.get(NotificationChannel, channel_id)
        if ch is None:
            raise HTTPException(404, "canal não encontrado")
        data = body.model_dump(exclude_unset=True)
        for k in ("enabled", "name"):
            if k in data and data[k] is not None:
                setattr(ch, k, data[k])
        cfg = dict(ch.config or {})
        for k in ("min_severity", "min_score"):
            if k in data and data[k] is not None:
                cfg[k] = data[k]
        ch.config = cfg
        audit.write(s, p, "channel.update", "channel", str(ch.id), {"changes": list(data)})
        return _channel_view(ch)


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles(*ADMIN))]) -> None:
    with tenant_session(p.tenant_id) as s:
        ch = s.get(NotificationChannel, channel_id)
        if ch is None:
            raise HTTPException(404, "canal não encontrado")
        s.delete(ch)
        audit.write(s, p, "channel.delete", "channel", str(channel_id), {"kind": ch.kind})


@router.post("/channels/{channel_id}/test", summary="Envia uma mensagem de teste agora e devolve o resultado")
def test_channel(channel_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles(*ADMIN))]) -> dict:
    from datetime import datetime, timezone

    with tenant_session(p.tenant_id) as s:
        ch = s.get(NotificationChannel, channel_id)
        if ch is None:
            raise HTTPException(404, "canal não encontrado")
        t = s.get(Tenant, p.tenant_id)
        secret = crypto.decrypt_secret(p.tenant_id, ch.secret_ciphertext) if ch.secret_ciphertext else None
        now = datetime.now(timezone.utc)
        try:
            if ch.kind in alert_rules.ALERT_KINDS:
                fake = Alert(id=uuid.uuid4(), rule="teste", severity="baixo", title="Mensagem de teste do PromptShield (sem dados reais)",
                             user_id="teste", department=None, count=1, first_seen=now, last_seen=now,
                             detail={"score": 0, "categories": []})
                notifier.send_alert(ch, notifier.alert_dict(fake, t.name), secret)
            else:
                rec = {"event_id": str(uuid.uuid4()), "occurred_at": now, "user_id": "teste", "department": None, "app": "teste",
                       "channel": "teste", "kind": "prompt", "personal_account": False, "categories": [], "risk_score": 0,
                       "reasons": [], "decision": "allow", "would_decide": "allow", "score_version": "teste",
                       "title": "Mensagem de teste do PromptShield (sem dados reais)"}
                notifier.send_event(ch, rec, secret)
            result = {"ok": True, "error": None}
        except notifier.DeliveryError as exc:
            result = {"ok": False, "error": str(exc)}
        audit.write(s, p, "channel.test", "channel", str(channel_id), result)
        return result
