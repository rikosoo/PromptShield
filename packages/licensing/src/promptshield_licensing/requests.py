"""Pedidos da instalação ao serviço de licenças (ativação e renovação), assinados com a chave PRIVADA da instalação.

O serviço confere a assinatura com a chave pública da instalação: prova que quem pede tem a chave (e não só o código).
Proteção contra repetição: janela de tempo curta + nonce único (o serviço guarda os nonces vistos)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .crypto import Installation, SignatureError, fingerprint, load_public_key, sign_blob, verify_blob

PREFIX = "pr1"
WINDOW = timedelta(minutes=5)


class RequestError(Exception):
    pass


def build_request(inst: Installation, typ: str, now: datetime, **fields: Any) -> str:
    payload = {"v": 1, "typ": typ, "installation_id": inst.installation_id, "public_key": inst.public_b64,
               "timestamp": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "nonce": secrets.token_urlsafe(16), **fields}
    return sign_blob(inst.private, PREFIX, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def verify_request(token: str, now: datetime, *, expected_public_key: str | None = None, window: timedelta = WINDOW) -> dict[str, Any]:
    """Devolve o conteúdo do pedido se a assinatura, o vínculo chave/identificador e o horário conferem. Não confere nonce nem o código."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise RequestError("formato inválido")
    try:
        from .crypto import b64d

        body = json.loads(b64d(parts[1]))
        if not isinstance(body, dict):
            raise RequestError("conteúdo inválido")
        pub_text = str(body["public_key"])
        verify_blob(load_public_key(pub_text), PREFIX, token)
        sent = datetime.strptime(body["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (SignatureError, KeyError, ValueError, TypeError) as exc:
        raise RequestError("pedido inválido") from exc
    if expected_public_key is not None and pub_text != expected_public_key:
        raise RequestError("a chave não é a da instalação cadastrada")
    if body.get("installation_id") != fingerprint(pub_text):
        raise RequestError("identificador não corresponde à chave")
    if abs(now - sent) > window:
        raise RequestError("pedido fora da janela de tempo (relógio da máquina errado ou pedido repetido)")
    if not isinstance(body.get("nonce"), str) or len(body["nonce"]) < 8:
        raise RequestError("sem nonce")
    return body
