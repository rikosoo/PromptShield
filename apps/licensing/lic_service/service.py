"""Regras do serviço de licenças. Funções recebem a sessão, o relógio e a chave; nada aqui lê variável de ambiente.

Fluxo: o fornecedor cadastra cliente e contrato (CLI), gera um código de ativação de uso único e curto, e o administrador do cliente o informa na
instalação. A instalação prova que tem a chave privada (pedido assinado), o contrato é vinculado à chave PÚBLICA dela e volta uma autorização
assinada. Depois a instalação renova (por exemplo, uma vez por dia) e recebe outra autorização de poucos dias. Nada é cobrado nem cortado aqui:
o estado do contrato é só o que o fornecedor decide (ativo ou encerrado) e a instalação interpreta com regras públicas (promptshield_licensing.states)."""
from __future__ import annotations

import calendar
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from promptshield_licensing import AuthorizationError, RequestError, b64d, issue_authorization, verify_request
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from lic_service.models import ActivationCode, AuditEntry, Contract, Customer, Installation, IssuedAuthorization, Nonce

CODE_PREFIX = "psa_"


class ServiceError(Exception):
    """Recusa de um pedido da instalação. `code` é estável (a instalação e os testes dependem dele); `detail` é para pessoas."""

    def __init__(self, code: str, detail: str, http: int = 400) -> None:
        super().__init__(detail)
        self.code, self.detail, self.http = code, detail, http


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year, month = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def audit(s: Session, actor: str, action: str, contract_id: Any = None, **detail: Any) -> None:
    s.add(AuditEntry(actor=actor, action=action, contract_id=contract_id, detail=detail))


# ---------------- comandos do fornecedor (CLI) ----------------
def create_customer(s: Session, name: str, email: str | None = None) -> Customer:
    c = Customer(name=name, contact_email=email)
    s.add(c)
    s.flush()
    audit(s, "fornecedor", "customer.create", name=name)
    return c


def create_contract(s: Session, customer: Customer, devices: int, months: int, *, tolerance_days: int = 15, on_end: str = "stop_inspection",
                    validity_days: int = 7, renew_hours: int = 24, note: str | None = None) -> Contract:
    k = Contract(customer_id=customer.id, max_devices=devices, term_months=months, tolerance_days=tolerance_days, on_end=on_end,
                 auth_validity_days=validity_days, renew_after_hours=renew_hours, note=note)
    s.add(k)
    s.flush()
    audit(s, "fornecedor", "contract.create", k.id, devices=devices, months=months, tolerance_days=tolerance_days, on_end=on_end)
    return k


def _active_installation(s: Session, contract_id: Any) -> Installation | None:
    return s.execute(select(Installation).where(Installation.contract_id == contract_id, Installation.unbound_at.is_(None))).scalar()


def issue_code(s: Session, contract: Contract, now: datetime, valid_days: int = 7) -> str:
    """Gera um código de uso único. O texto aparece só aqui: no banco fica o hash."""
    if contract.status == "encerrado":
        raise ServiceError("contract_closed", "contrato encerrado: reabra antes de gerar código")
    if _active_installation(s, contract.id) is not None:
        raise ServiceError("already_bound", "este contrato já tem uma instalação vinculada; use 'unbind' antes de gerar um código novo")
    if not 1 <= valid_days <= 30:
        raise ServiceError("bad_validity", "a validade do código vai de 1 a 30 dias")
    prefix = secrets.token_hex(4)
    code = f"{CODE_PREFIX}{prefix}_{secrets.token_urlsafe(24)}"
    s.add(ActivationCode(contract_id=contract.id, prefix=f"{CODE_PREFIX}{prefix}", code_hash=hash_code(code), expires_at=now + timedelta(days=valid_days)))
    audit(s, "fornecedor", "code.issue", contract.id, prefix=f"{CODE_PREFIX}{prefix}", valid_days=valid_days)
    return code


def close_contract(s: Session, contract: Contract, reason: str, now: datetime) -> None:
    contract.status, contract.closed_at, contract.close_reason = "encerrado", now, reason[:300]
    audit(s, "fornecedor", "contract.close", contract.id, reason=reason[:300])


def reopen_contract(s: Session, contract: Contract, now: datetime) -> None:
    if contract.status != "encerrado":
        raise ServiceError("not_closed", "o contrato não está encerrado")
    if contract.ends_at and now > contract.ends_at + timedelta(days=contract.tolerance_days):
        raise ServiceError("contract_expired", "o prazo do contrato (com tolerância) já passou: estenda antes de reabrir")
    contract.status = "ativo" if contract.starts_at else "pendente"
    contract.closed_at = contract.close_reason = None
    audit(s, "fornecedor", "contract.reopen", contract.id)


def extend_contract(s: Session, contract: Contract, months: int) -> None:
    """Renovação do contrato (administrada à mão): empurra o fim. A instalação percebe na próxima renovação da autorização."""
    if months <= 0:
        raise ServiceError("bad_months", "informe meses positivos")
    if contract.ends_at:
        contract.ends_at = add_months(contract.ends_at, months)      # já ativado: empurra o fim
    else:
        contract.term_months += months                                # ainda pendente: o prazo conta a partir da ativação
    audit(s, "fornecedor", "contract.extend", contract.id, months=months, ends_at=contract.ends_at.isoformat() if contract.ends_at else None)


def set_devices(s: Session, contract: Contract, devices: int) -> None:
    contract.max_devices = devices
    audit(s, "fornecedor", "contract.devices", contract.id, devices=devices)


def unbind(s: Session, contract: Contract, now: datetime) -> None:
    """Desvincula a instalação (troca de servidor, recuperação de desastre). Exige um código novo para vincular de novo."""
    inst = _active_installation(s, contract.id)
    if inst is None:
        raise ServiceError("no_installation", "nenhuma instalação vinculada")
    inst.unbound_at = now
    audit(s, "fornecedor", "installation.unbind", contract.id, installation=inst.installation_id)


# ---------------- protocolo com a instalação ----------------
def _peek_installation_id(token: str) -> str | None:
    try:
        body = json.loads(b64d(token.split(".")[1]))
        return str(body["installation_id"])
    except Exception:  # noqa: BLE001 - qualquer lixo vira "não reconhecida"
        return None


def _consume_nonce(s: Session, nonce: str, now: datetime) -> None:
    s.execute(delete(Nonce).where(Nonce.seen_at < now - timedelta(hours=1)))
    got = s.execute(insert(Nonce).values(nonce=nonce, seen_at=now).on_conflict_do_nothing(index_elements=["nonce"]).returning(Nonce.nonce)).scalar()
    if got is None:
        raise ServiceError("replay", "pedido repetido", 400)


def _issue(s: Session, key: Ed25519PrivateKey, contract: Contract, inst: Installation, kind: str, now: datetime) -> str:
    serial = (s.execute(select(func.max(IssuedAuthorization.serial)).where(IssuedAuthorization.contract_id == contract.id)).scalar() or 0) + 1
    customer = s.get(Customer, contract.customer_id)
    status = "active" if contract.status == "ativo" else "closed"
    if contract.starts_at is None or contract.ends_at is None:
        raise ServiceError("contract_not_active", "contrato ainda não ativado", 403)
    try:
        token, auth = issue_authorization(key, license_id=str(contract.id), installation_id=inst.installation_id, customer=customer.name,
                                          max_devices=contract.max_devices, contract_start=contract.starts_at, contract_end=contract.ends_at,
                                          tolerance_days=contract.tolerance_days, status=status, on_end=contract.on_end, serial=serial, now=now,
                                          validity=timedelta(days=contract.auth_validity_days), renew_after_hours=contract.renew_after_hours)
    except AuthorizationError as exc:
        raise ServiceError("contract_expired", "o contrato passou do prazo com a tolerância; fale com o fornecedor", 403) from exc
    s.add(IssuedAuthorization(contract_id=contract.id, installation_id=inst.installation_id, serial=serial, kind=kind, status=status, issued_at=now,
                              auth_expires=auth.auth_expires, token_sha256=hashlib.sha256(token.encode()).hexdigest()))
    return token


def activate(s: Session, key: Ed25519PrivateKey, token: str, now: datetime) -> str:
    try:
        body = verify_request(token, now)
    except RequestError as exc:
        raise ServiceError("invalid_request", str(exc)) from exc
    if body.get("typ") != "activate" or not isinstance(body.get("code"), str):
        raise ServiceError("invalid_request", "pedido de ativação malformado")
    _consume_nonce(s, body["nonce"], now)
    ac = s.execute(select(ActivationCode).where(ActivationCode.code_hash == hash_code(body["code"])).with_for_update()).scalar()
    if ac is None:
        raise ServiceError("invalid_code", "código de ativação inválido")
    if ac.used_at is not None:
        raise ServiceError("code_used", "este código já foi usado")
    if ac.expires_at <= now:
        raise ServiceError("code_expired", "este código expirou; peça um novo ao fornecedor")
    contract = s.execute(select(Contract).where(Contract.id == ac.contract_id).with_for_update()).scalar_one()
    if contract.status == "encerrado":
        raise ServiceError("contract_closed", "este contrato está encerrado", 403)
    if _active_installation(s, contract.id) is not None:
        raise ServiceError("already_bound", "este contrato já tem uma instalação vinculada", 409)
    existing = s.execute(select(Installation).where(Installation.installation_id == body["installation_id"])).scalar()
    if existing is not None and existing.contract_id != contract.id:
        raise ServiceError("installation_in_use", "esta instalação já está vinculada a outro contrato", 409)
    if contract.status == "pendente":
        contract.status, contract.starts_at, contract.ends_at = "ativo", now, add_months(now, contract.term_months)
    ac.used_at, ac.used_by_installation = now, body["installation_id"]
    if existing is not None:
        inst, inst.unbound_at = existing, None
        inst.public_key = body["public_key"]
    else:
        inst = Installation(contract_id=contract.id, installation_id=body["installation_id"], public_key=body["public_key"])
        s.add(inst)
    inst.hostname, inst.product_version, inst.last_seen_at = str(body.get("hostname") or "")[:200] or None, str(body.get("version") or "")[:40] or None, now
    s.flush()
    out = _issue(s, key, contract, inst, "activation", now)
    audit(s, inst.installation_id, "installation.activate", contract.id, code_prefix=ac.prefix, hostname=inst.hostname)
    return out


def renew(s: Session, key: Ed25519PrivateKey, token: str, now: datetime) -> str:
    iid = _peek_installation_id(token)
    inst = s.execute(select(Installation).where(Installation.installation_id == iid, Installation.unbound_at.is_(None)).with_for_update()).scalar() if iid else None
    if inst is None:
        raise ServiceError("unknown_installation", "instalação não reconhecida", 403)
    try:
        body = verify_request(token, now, expected_public_key=inst.public_key)
    except RequestError as exc:
        raise ServiceError("invalid_request", str(exc)) from exc
    if body.get("typ") != "renew":
        raise ServiceError("invalid_request", "pedido de renovação malformado")
    _consume_nonce(s, body["nonce"], now)
    contract = s.execute(select(Contract).where(Contract.id == inst.contract_id).with_for_update()).scalar_one()
    count = body.get("device_count")
    inst.last_seen_at = now
    inst.last_device_count = count if isinstance(count, int) and 0 <= count <= 10_000_000 else inst.last_device_count
    inst.product_version = str(body.get("version") or inst.product_version or "")[:40] or None
    out = _issue(s, key, contract, inst, "renewal", now)
    audit(s, inst.installation_id, "installation.renew", contract.id, device_count=inst.last_device_count, contract_status=contract.status)
    return out


def record_refusal(s: Session, action: str, code: str, **detail: Any) -> None:
    """Recusas ficam na auditoria (em outra transação, porque a do pedido foi desfeita)."""
    audit(s, "instalacao", action, None, code=code, **detail)
