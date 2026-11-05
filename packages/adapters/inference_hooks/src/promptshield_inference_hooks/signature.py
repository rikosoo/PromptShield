"""Verificação de assinatura no padrão Standard Webhooks, como descrito na documentação dos inference hooks.

HMAC-SHA256 de `{webhook-id}.{webhook-timestamp}.{corpo em bytes}`; chave = base64 PADRÃO do que vem depois de `whsec_`;
`webhook-signature` pode trazer vários `v1,<base64>` separados por espaço; tolerância de 5 minutos nos dois sentidos.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping, Sequence

TOLERANCE_SECONDS = 300


class SignatureError(Exception):
    """A requisição não é verificável. A mensagem é segura para log (sem segredos nem conteúdo)."""


def _key(secret: str) -> bytes:
    raw = secret[6:] if secret.startswith("whsec_") else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("segredo de assinatura mal formado") from exc


def verify(secrets: Sequence[str], headers: Mapping[str, str], body: bytes, now: float | None = None) -> None:
    """Levanta SignatureError se nenhum dos segredos validar. Aceita vários (troca de segredo: o novo e o anterior)."""
    lowered = {k.lower(): v for k, v in headers.items()}
    try:
        message_id, timestamp, signatures = lowered["webhook-id"], lowered["webhook-timestamp"], lowered["webhook-signature"]
    except KeyError as exc:
        raise SignatureError("requisição sem assinatura") from exc
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise SignatureError("timestamp inválido") from exc
    if abs((time.time() if now is None else now) - signed_at) > TOLERANCE_SECONDS:
        raise SignatureError("timestamp fora da tolerância de 5 minutos")
    if not secrets:
        raise SignatureError("nenhum segredo configurado")
    payload = f"{message_id}.{timestamp}.".encode() + body
    candidates = [c.encode() for c in signatures.split()]
    for secret in secrets:
        try:
            key = _key(secret)
        except SignatureError:
            continue
        expected = b"v1," + base64.b64encode(hmac.new(key, payload, hashlib.sha256).digest())
        if any(hmac.compare_digest(expected, c) for c in candidates):  # bytes: str não-ASCII levantaria erro
            return
    raise SignatureError("assinatura inválida")


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    """Só para testes e para o script de medição: gera o cabeçalho `webhook-signature` como a Anthropic geraria."""
    payload = f"{message_id}.{timestamp}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(_key(secret), payload, hashlib.sha256).digest()).decode()
