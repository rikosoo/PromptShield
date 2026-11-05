"""Autorização assinada: o que o serviço de licenças entrega à instalação do cliente.

Dois prazos DIFERENTES:
- contrato (`contract_start`..`contract_end`): até quando o cliente tem direito ao produto;
- autorização (`auth_expires`): por quanto tempo a instalação funciona sem falar com o fornecedor.
Regra: para uma autorização ativa, `auth_expires` nunca passa de `contract_end` + `tolerance_days` (tolerância explícita no contrato)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .crypto import SignatureError, sign_blob, verify_blob

PREFIX = "pl1"
PRODUCT = "promptshield"
Status = Literal["active", "closed"]
OnEnd = Literal["stop_inspection", "keep_inspection"]


class AuthorizationError(Exception):
    """Autorização inválida: assinatura, instalação, formato ou regra dos prazos."""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise AuthorizationError(f"data inválida: {text!r}") from exc


@dataclass(frozen=True)
class Authorization:
    license_id: str
    installation_id: str
    customer: str
    max_devices: int
    contract_start: datetime
    contract_end: datetime
    tolerance_days: int
    status: Status
    on_end: OnEnd
    issued_at: datetime
    not_before: datetime
    auth_expires: datetime
    serial: int
    renew_after_hours: int

    @property
    def tolerance_end(self) -> datetime:
        return self.contract_end + timedelta(days=self.tolerance_days)

    def to_claims(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("contract_start", "contract_end", "issued_at", "not_before", "auth_expires"):
            d[k] = _iso(d[k])
        return {"v": 1, "typ": "authorization", "product": PRODUCT, **d}


def issue_authorization(key: Ed25519PrivateKey, *, license_id: str, installation_id: str, customer: str, max_devices: int,
                        contract_start: datetime, contract_end: datetime, tolerance_days: int, status: Status, on_end: OnEnd,
                        serial: int, now: datetime, validity: timedelta, renew_after_hours: int = 24) -> tuple[str, Authorization]:
    """Assina uma autorização. Ativa: a validade é cortada no fim do contrato + tolerância. Encerrada: só informa (validade curta)."""
    if contract_end <= contract_start:
        raise AuthorizationError("o fim do contrato precisa ser depois do início")
    if tolerance_days < 0 or max_devices < 0:
        raise AuthorizationError("tolerância e limite de máquinas não podem ser negativos")
    expires = now + validity
    if status == "active":
        expires = min(expires, contract_end + timedelta(days=tolerance_days))
        if expires <= now:
            raise AuthorizationError("o contrato já passou do fim da tolerância: não se emite autorização ativa")
    auth = Authorization(license_id=license_id, installation_id=installation_id, customer=customer, max_devices=max_devices,
                         contract_start=contract_start, contract_end=contract_end, tolerance_days=tolerance_days, status=status, on_end=on_end,
                         issued_at=now, not_before=now, auth_expires=expires, serial=serial, renew_after_hours=renew_after_hours)
    payload = json.dumps(auth.to_claims(), sort_keys=True, separators=(",", ":")).encode()
    return sign_blob(key, PREFIX, payload), auth


def verify_authorization(token: str, pub: Ed25519PublicKey, installation_id: str, now: datetime, *, min_serial: int = 0,
                         skew: timedelta = timedelta(minutes=10)) -> Authorization:
    """Confere assinatura, vínculo com ESTA instalação e as regras dos prazos. NÃO confere se já expirou: quem decide o estado é `evaluate`."""
    try:
        claims = json.loads(verify_blob(pub, PREFIX, token))
    except SignatureError as exc:
        raise AuthorizationError(str(exc)) from exc
    except ValueError as exc:
        raise AuthorizationError("conteúdo ilegível") from exc
    if not isinstance(claims, dict) or claims.get("typ") != "authorization" or claims.get("v") != 1 or claims.get("product") != PRODUCT:
        raise AuthorizationError("não é uma autorização deste produto")
    try:
        a = Authorization(
            license_id=str(claims["license_id"]), installation_id=str(claims["installation_id"]), customer=str(claims["customer"]),
            max_devices=int(claims["max_devices"]), contract_start=_parse(claims["contract_start"]), contract_end=_parse(claims["contract_end"]),
            tolerance_days=int(claims["tolerance_days"]), status=claims["status"], on_end=claims["on_end"], issued_at=_parse(claims["issued_at"]),
            not_before=_parse(claims["not_before"]), auth_expires=_parse(claims["auth_expires"]), serial=int(claims["serial"]),
            renew_after_hours=int(claims["renew_after_hours"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorizationError("campos faltando ou inválidos") from exc
    if a.status not in ("active", "closed") or a.on_end not in ("stop_inspection", "keep_inspection"):
        raise AuthorizationError("status ou política de término inválidos")
    if a.installation_id != installation_id:
        raise AuthorizationError("a autorização é de outra instalação")
    if a.not_before > now + skew:
        raise AuthorizationError("a autorização ainda não vale (relógio atrasado ou data futura)")
    if a.serial < min_serial:
        raise AuthorizationError("autorização mais antiga do que a já recebida")
    if a.status == "active" and a.auth_expires > a.tolerance_end:
        raise AuthorizationError("a autorização passa do fim do contrato mais a tolerância")
    return a
