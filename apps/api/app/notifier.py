"""Envio de notificações a partir da fila (outbox): webhook genérico, Slack, Teams, e-mail, syslog/CEF e webhook de SIEM.

Estado de cada integração (princípio 1):
  webhook genérico / siem_webhook  REAL no que o código controla: JSON assinado com HMAC-SHA256 (testado contra um servidor local).
  slack      PARCIAL: formato `{"text": ...}` conforme a documentação oficial; não testado contra um Slack real.
  teams      EXPERIMENTAL / A VERIFICAR: as conexões Office 365 foram aposentadas; o formato do webhook de Workflows
             (cartão adaptável em `attachments`) não pôde ser conferido na documentação da Microsoft neste ambiente.
  email      PARCIAL: SMTP padrão (smtplib); testado só contra um servidor SMTP de teste local.
  syslog_cef PARCIAL: RFC 5424 sobre UDP ou TCP (TCP com uma mensagem por linha); A VERIFICAR com o receptor do cliente.

Segurança: destinos precisam ser https e públicos (proteção contra SSRF), a conexão é feita no IP validado (sem redirecionar)
e as mensagens nunca levam o texto do prompt, só metadados. URLs de webhook (que são segredos) nunca entram em logs ou erros.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import smtplib
import socket
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select, text

from app import cef, crypto
from app.config import settings
from app.db import tenant_session
from app.models import Alert, Analysis, Event, NotificationChannel, OutboxItem, Tenant
from app.siem import event_record, json_safe

STATUS = {"webhook": "real", "siem_webhook": "real", "slack": "parcial", "teams": "experimental", "email": "parcial",
          "syslog_cef": "parcial"}
BACKOFF_SECONDS = 30


class DeliveryError(Exception):
    """Mensagem curta e segura (sem URL nem conteúdo)."""


# ---------- validação de destino ----------
def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DeliveryError("nome do destino não resolve") from exc
    ips = sorted({i[4][0] for i in infos})
    if not settings.allow_private_webhook_targets:
        for ip in ips:
            if not ipaddress.ip_address(ip.split("%")[0]).is_global:
                raise DeliveryError("destino bloqueado: endereço não é público")
    return ips


def validate_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or (parts.scheme == "http" and not settings.allow_insecure_webhooks):
        raise DeliveryError("use uma URL https")
    if not parts.hostname:
        raise DeliveryError("URL sem host")
    _resolve(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))


def validate_target(kind: str, target: str) -> None:
    """Chamado ao criar o canal: erro de configuração aparece na hora, não só no primeiro alerta."""
    if kind in ("webhook", "slack", "teams", "siem_webhook"):
        validate_url(target)
    elif kind == "email":
        if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", target):
            raise DeliveryError("e-mail inválido")
    elif kind == "syslog_cef":
        host, _, port = target.rpartition(":")
        if not host or not port.isdigit() or not (0 < int(port) < 65536):
            raise DeliveryError("use host:porta")
        _resolve(host, int(port))
    else:
        raise DeliveryError("tipo de canal desconhecido")


# ---------- transporte ----------
class _Pinned:
    """Conexão feita no IP já validado (evita trocar o DNS entre a checagem e o uso)."""

    @staticmethod
    def open(scheme: str, host: str, port: int, ip: str, timeout: float):
        if scheme == "https":
            ctx = ssl.create_default_context()

            class Conn(HTTPSConnection):
                def connect(self) -> None:  # noqa: D102
                    sock = socket.create_connection((ip, port), timeout=timeout)
                    self.sock = ctx.wrap_socket(sock, server_hostname=host)

            return Conn(host, port, timeout=timeout)

        class PlainConn(HTTPConnection):
            def connect(self) -> None:  # noqa: D102
                self.sock = socket.create_connection((ip, port), timeout=timeout)

        return PlainConn(host, port, timeout=timeout)


def post_json(url: str, body: bytes, headers: dict[str, str]) -> None:
    parts = urlsplit(url)
    validate_url(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ip = _resolve(parts.hostname or "", port)[0]
    conn = _Pinned.open(parts.scheme, parts.hostname or "", port, ip, settings.webhook_timeout_seconds)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "User-Agent": "PromptShield", **headers})
        resp = conn.getresponse()
        resp.read(1024)
        if not 200 <= resp.status < 300:  # 3xx não é seguido de propósito
            raise DeliveryError(f"o destino respondeu HTTP {resp.status}")
    except DeliveryError:
        raise
    except (OSError, ssl.SSLError) as exc:
        raise DeliveryError(f"falha de conexão ({type(exc).__name__})") from exc
    finally:
        conn.close()


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def _signed_headers(secret: str | None, body: bytes) -> dict[str, str]:
    if not secret:
        return {}
    ts = str(int(time.time()))
    return {"X-PromptShield-Timestamp": ts, "X-PromptShield-Signature": sign(secret, ts, body)}


def send_syslog(target: str, proto: str, line: str) -> None:
    host, _, port = target.rpartition(":")
    ip = _resolve(host, int(port))[0]
    data = line.replace("\n", " ").encode("utf-8")
    try:
        if proto == "tcp":
            with socket.create_connection((ip, int(port)), timeout=settings.webhook_timeout_seconds) as s:
                s.sendall(data + b"\n")
        else:
            with socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(settings.webhook_timeout_seconds)
                s.sendto(data, (ip, int(port)))
    except OSError as exc:
        raise DeliveryError(f"falha de conexão ({type(exc).__name__})") from exc


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise DeliveryError("SMTP não configurado (defina SMTP_HOST)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.webhook_timeout_seconds) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"falha no envio SMTP ({type(exc).__name__})") from exc


def channel_target(ch: NotificationChannel) -> str:
    """Destino completo (URLs de webhook ficam cifradas no banco; `ch.target` guarda só o host para exibição)."""
    return crypto.decrypt_secret(ch.tenant_id, ch.target_ciphertext) if ch.target_ciphertext else ch.target


# ---------- mensagens ----------
def alert_dict(a: Alert, tenant_name: str) -> dict[str, Any]:
    d = a.detail or {}
    link = f"{settings.console_url.rstrip('/')}/incidents/{a.incident_id}" if settings.console_url and a.incident_id else None
    return {"id": str(a.id), "tenant": tenant_name, "rule": a.rule, "severity": a.severity, "title": a.title,
            "user_id": a.user_id, "department": a.department, "count": a.count, "first_seen": a.first_seen.isoformat(),
            "last_seen": a.last_seen.isoformat(), "score": d.get("score"), "categories": d.get("categories", []),
            "incident_id": str(a.incident_id) if a.incident_id else None, "console_link": link,
            "note": "Indicador de risco, requer revisão humana."}


def plain(value: object, limit: int = 200) -> str:
    """Campos que o CLIENTE controla (user_id, departamento, título) entram em Slack/Teams/e-mail: sem quebra de linha ou controle e sem
    <, > e & (no Slack, `<!channel>` e `<https://...|texto>` viram menção e link; escapar é o que a documentação do Slack pede)."""
    t = "".join(" " if ch in "\r\n\t" or ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 else ch for ch in str(value))
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:limit]


def alert_text(d: dict[str, Any]) -> str:
    lines = [f"[PromptShield] {d['severity'].upper()}: {plain(d['title'])}", f"Usuário: {plain(d['user_id'])}"
             + (f" ({plain(d['department'], 120)})" if d["department"] else ""), f"Risco: {d['score']}  Categorias: {', '.join(d['categories']) or '-'}"]
    if d["console_link"]:
        lines.append(f"Console: {d['console_link']}")
    lines.append(d["note"] + " Esta mensagem não traz o texto do prompt.")
    return "\n".join(lines)


def send_alert(ch: NotificationChannel, d: dict[str, Any], secret: str | None) -> None:
    text_msg = alert_text(d)
    if ch.kind == "email":
        send_email(channel_target(ch), f"[PromptShield] {d['severity']}: {plain(d['title'])}", text_msg)
    elif ch.kind == "slack":
        post_json(channel_target(ch), json.dumps({"text": text_msg}).encode(), {})
    elif ch.kind == "teams":  # EXPERIMENTAL / A VERIFICAR (ver docs/siem.md)
        card = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "text": text_msg, "wrap": True}]}}]}
        post_json(channel_target(ch), json.dumps(card).encode(), {})
    else:  # webhook genérico
        body = json.dumps({"schema": "promptshield.alert.v1", "alert": d}, sort_keys=True).encode()
        post_json(channel_target(ch), body, _signed_headers(secret, body))


def send_event(ch: NotificationChannel, rec: dict[str, Any], secret: str | None) -> None:
    if ch.kind == "syslog_cef":
        line = cef.syslog_5424(cef.event_to_cef(rec, settings_version()), when=rec["occurred_at"])
        send_syslog(channel_target(ch), (ch.config or {}).get("proto", "udp"), line)
    else:
        body = json.dumps({"schema": "promptshield.event.v1", "event": json_safe(rec)}, sort_keys=True).encode()
        post_json(channel_target(ch), body, _signed_headers(secret, body))


def settings_version() -> str:
    return settings.version


# ---------- fila ----------
def deliver_pending(tenant_id: uuid.UUID, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    counts = {"sent": 0, "retry": 0, "failed": 0}
    with tenant_session(tenant_id) as s:
        tenant = s.get(Tenant, tenant_id)
        items = s.execute(select(OutboxItem).where(OutboxItem.status == "pending", OutboxItem.next_attempt_at <= now)
                          .order_by(OutboxItem.created_at).limit(limit).with_for_update(skip_locked=True)).scalars().all()
        for it in items:
            ch = s.get(NotificationChannel, it.channel_id)
            try:
                if ch is None or not ch.enabled:
                    raise DeliveryError("canal desativado ou removido")
                secret = crypto.decrypt_secret(tenant_id, ch.secret_ciphertext) if ch.secret_ciphertext else None
                if it.kind == "alert":
                    a = s.get(Alert, it.ref_id)
                    if a is None:
                        raise DeliveryError("alerta removido")
                    send_alert(ch, alert_dict(a, tenant.name if tenant else ""), secret)
                else:
                    row = s.execute(select(Event, Analysis).join(Analysis, Analysis.event_pk == Event.id)
                                    .where(Event.id == it.ref_id)).first()
                    if row is None:
                        raise DeliveryError("evento removido")
                    send_event(ch, event_record(*row), secret)
                it.status, it.sent_at, it.last_error = "sent", now, None
                counts["sent"] += 1
            except DeliveryError as exc:
                it.attempts += 1
                it.last_error = str(exc)[:500]
                if it.attempts >= settings.outbox_max_attempts:
                    it.status = "failed"
                    counts["failed"] += 1
                else:
                    it.next_attempt_at = now + timedelta(seconds=BACKOFF_SECONDS * 2 ** (it.attempts - 1))
                    counts["retry"] += 1
    return counts


def deliver_all(limit: int = 100) -> dict[str, int]:
    from app.db import anonymous_session

    with anonymous_session() as s:
        ids = [r.tenant_id for r in s.execute(text("SELECT tenant_id FROM list_tenant_ids()"))]
    total = {"sent": 0, "retry": 0, "failed": 0}
    for tid in ids:
        for k, v in deliver_pending(tid, limit=limit).items():
            total[k] += v
    return total


def send_email_with_attachment(to: str, subject: str, body: str, filename: str, data: bytes, mime: str) -> None:
    if not settings.smtp_host:
        raise DeliveryError("SMTP não configurado (defina SMTP_HOST)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    maintype, _, subtype = mime.split(";")[0].partition("/")
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.webhook_timeout_seconds) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"falha no envio SMTP ({type(exc).__name__})") from exc
