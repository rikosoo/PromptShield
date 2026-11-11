"""Regras do serviço de licenças. Funções recebem a sessão, o relógio e a chave; nada aqui lê variável de ambiente.

Fluxo: o fornecedor cadastra cliente e contrato (CLI), gera um código de ativação de uso único e curto, e o administrador do cliente o informa na
instalação. A instalação prova que tem a chave privada (pedido assinado), o contrato é vinculado à chave PÚBLICA dela e volta uma autorização
assinada. Depois a instalação renova (por exemplo, uma vez por dia) e recebe outra autorização de poucos dias. Nada é cobrado nem cortado aqui:
o estado do contrato é só o que o fornecedor decide (ativo ou encerrado) e a instalação interpreta com regras públicas (promptshield_licensing.states)."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from promptshield_licensing import AuthorizationError, RequestError, b64d, issue_authorization, verify_request
from promptshield_licensing.authorization import check_silence_rule
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from lic_service.models import ActivationCode, AuditEntry, Contract, Customer, Installation, IssuedAuthorization, Nonce

CODE_PREFIX = "psa_"
# política SEMANAL recomendada (decidida pelo dono em 2026-11-11): valida toda semana; se uma validação falhar, o fornecedor vê na hora (painel), o cliente é
# avisado 10 dias depois e a inspeção é suspensa 21 dias depois (contados do momento em que a validação era esperada). Autorização cobre 7 + 21 dias.
DEFAULT_RENEW_HOURS, DEFAULT_WARN_DAYS, DEFAULT_SUSPEND_DAYS, DEFAULT_VALIDITY_DAYS = 168, 10, 21, 28
INTERNAL_ALERT_AFTER = timedelta(hours=12)          # atraso na validação a partir do qual o FORNECEDOR é alertado (uma tentativa atrasada à toa não alarma)


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
def create_customer(s: Session, name: str, email: str | None = None, *, actor: str = "fornecedor") -> Customer:
    c = Customer(name=name, contact_email=email)
    s.add(c)
    s.flush()
    audit(s, actor, "customer.create", name=name)
    return c


def check_terms(renew_after_hours: int, validity_days: int, warn: int | None, suspend: int | None) -> None:
    """Coerência dos prazos de um contrato. A autorização precisa durar a cadência + a suspensão, senão ela venceria antes da suspensão."""
    try:
        check_silence_rule(warn, suspend)
    except AuthorizationError as exc:
        raise ServiceError("bad_silence_rule", str(exc)) from exc
    if not 1 <= renew_after_hours <= 24 * 90:
        raise ServiceError("bad_cadence", "a cadência de validação vai de 1 hora a 90 dias")
    if validity_days < 1:
        raise ServiceError("bad_validity", "a validade da autorização precisa ser de pelo menos 1 dia")
    if suspend is not None and validity_days < math.ceil(renew_after_hours / 24) + suspend:
        raise ServiceError("bad_validity", f"a validade da autorização ({validity_days} dias) precisa cobrir a cadência ({math.ceil(renew_after_hours / 24)} dias) "
                                           f"mais a suspensão ({suspend} dias)")


def create_contract(s: Session, customer: Customer, devices: int, months: int, *, tolerance_days: int = 15, on_end: str = "stop_inspection",
                    validity_days: int = 7, renew_hours: int = 24, note: str | None = None, warn_after_days: int | None = None,
                    suspend_after_days: int | None = None, actor: str = "fornecedor") -> Contract:
    check_terms(renew_hours, validity_days, warn_after_days, suspend_after_days)
    k = Contract(customer_id=customer.id, max_devices=devices, term_months=months, tolerance_days=tolerance_days, on_end=on_end,
                 auth_validity_days=validity_days, renew_after_hours=renew_hours, note=note, warn_after_days=warn_after_days,
                 suspend_after_days=suspend_after_days)
    s.add(k)
    s.flush()
    audit(s, actor, "contract.create", k.id, devices=devices, months=months, tolerance_days=tolerance_days, on_end=on_end, renew_hours=renew_hours,
          validity_days=validity_days, warn_after_days=warn_after_days, suspend_after_days=suspend_after_days)
    return k


def create_weekly_contract(s: Session, customer: Customer, devices: int, months: int, *, tolerance_days: int = 15, on_end: str = "stop_inspection",
                           note: str | None = None, actor: str = "fornecedor") -> Contract:
    """Contrato com a política semanal recomendada (validação toda semana, aviso ao cliente em 10 dias, suspensão em 21)."""
    return create_contract(s, customer, devices, months, tolerance_days=tolerance_days, on_end=on_end, validity_days=DEFAULT_VALIDITY_DAYS,
                           renew_hours=DEFAULT_RENEW_HOURS, note=note, warn_after_days=DEFAULT_WARN_DAYS, suspend_after_days=DEFAULT_SUSPEND_DAYS, actor=actor)


def _active_installation(s: Session, contract_id: Any) -> Installation | None:
    return s.execute(select(Installation).where(Installation.contract_id == contract_id, Installation.unbound_at.is_(None))).scalar()


def issue_code(s: Session, contract: Contract, now: datetime, valid_days: int = 7, *, actor: str = "fornecedor") -> str:
    """Gera um código de uso único. O texto aparece só aqui: no banco fica o hash."""
    if contract.status == "encerrado":
        raise ServiceError("contract_closed", "contrato encerrado: reabra antes de gerar código")
    if _active_installation(s, contract.id) is not None:
        raise ServiceError("already_bound", "este contrato já tem uma instalação vinculada; use 'unbind' antes de gerar um código novo")
    if not 1 <= valid_days <= 30:
        raise ServiceError("bad_validity", "a validade do código vai de 1 a 30 dias")
    revoked = s.execute(update(ActivationCode).where(ActivationCode.contract_id == contract.id, ActivationCode.used_at.is_(None),
                                                      ActivationCode.expires_at > now).values(expires_at=now)).rowcount        # um código novo cancela os anteriores sem uso
    prefix = secrets.token_hex(4)
    code = f"{CODE_PREFIX}{prefix}_{secrets.token_urlsafe(24)}"
    s.add(ActivationCode(contract_id=contract.id, prefix=f"{CODE_PREFIX}{prefix}", code_hash=hash_code(code), expires_at=now + timedelta(days=valid_days)))
    audit(s, actor, "code.issue", contract.id, prefix=f"{CODE_PREFIX}{prefix}", valid_days=valid_days, revoked_previous=revoked)
    return code


def close_contract(s: Session, contract: Contract, reason: str, now: datetime, *, actor: str = "fornecedor") -> None:
    contract.status, contract.closed_at, contract.close_reason = "encerrado", now, reason[:300]
    audit(s, actor, "contract.close", contract.id, reason=reason[:300])


def reopen_contract(s: Session, contract: Contract, now: datetime, *, actor: str = "fornecedor") -> None:
    if contract.status != "encerrado":
        raise ServiceError("not_closed", "o contrato não está encerrado")
    if contract.ends_at and now > contract.ends_at + timedelta(days=contract.tolerance_days):
        raise ServiceError("contract_expired", "o prazo do contrato (com tolerância) já passou: estenda antes de reabrir")
    contract.status = "ativo" if contract.starts_at else "pendente"
    contract.closed_at = contract.close_reason = None
    audit(s, actor, "contract.reopen", contract.id)


def extend_contract(s: Session, contract: Contract, months: int, *, actor: str = "fornecedor") -> None:
    """Renovação do contrato (administrada à mão): empurra o fim. A instalação percebe na próxima renovação da autorização."""
    if months <= 0:
        raise ServiceError("bad_months", "informe meses positivos")
    if contract.ends_at:
        contract.ends_at = add_months(contract.ends_at, months)      # já ativado: empurra o fim
    else:
        contract.term_months += months                                # ainda pendente: o prazo conta a partir da ativação
    audit(s, actor, "contract.extend", contract.id, months=months, ends_at=contract.ends_at.isoformat() if contract.ends_at else None)


def set_devices(s: Session, contract: Contract, devices: int, *, actor: str = "fornecedor") -> None:
    contract.max_devices = devices
    audit(s, actor, "contract.devices", contract.id, devices=devices)


def days_left(contract: Contract, now: datetime) -> int | None:
    """Dias inteiros até o fim do contrato (negativo se já passou); None se ainda não foi ativado."""
    return None if contract.ends_at is None else math.floor((contract.ends_at - now).total_seconds() / 86400)


def set_end_date(s: Session, contract: Contract, new_end: datetime, reason: str, now: datetime, *, actor: str = "fornecedor") -> None:
    """Define o FIM do contrato (editar os dias restantes). Exige motivo; a instalação percebe na próxima validação. Só vale depois da ativação."""
    if contract.starts_at is None or contract.ends_at is None:
        raise ServiceError("not_activated", "o prazo só começa na ativação; antes disso ajuste a duração em meses")
    if len(reason.strip()) < 3:
        raise ServiceError("reason_required", "informe o motivo da alteração")
    if new_end <= contract.starts_at:
        raise ServiceError("bad_end", "o fim precisa ser depois do início do contrato")
    if new_end > now + timedelta(days=365 * 10):
        raise ServiceError("bad_end", "o fim não pode passar de 10 anos a partir de hoje")
    before = contract.ends_at
    contract.ends_at = new_end
    audit(s, actor, "contract.set_end", contract.id, before=before.isoformat(), after=new_end.isoformat(), reason=reason.strip()[:300])


def add_days(s: Session, contract: Contract, days: int, reason: str, now: datetime, *, actor: str = "fornecedor") -> None:
    """Soma (ou tira, se negativo) dias ao fim do contrato."""
    if contract.ends_at is None:
        raise ServiceError("not_activated", "o prazo só começa na ativação; antes disso ajuste a duração em meses")
    if days == 0:
        raise ServiceError("bad_days", "informe um número de dias diferente de zero")
    set_end_date(s, contract, contract.ends_at + timedelta(days=days), reason, now, actor=actor)


def set_term_months(s: Session, contract: Contract, months: int, *, actor: str = "fornecedor") -> None:
    if contract.starts_at is not None:
        raise ServiceError("already_active", "o contrato já foi ativado; edite a data de fim")
    if not 1 <= months <= 120:
        raise ServiceError("bad_months", "a duração vai de 1 a 120 meses")
    before = contract.term_months
    contract.term_months = months
    audit(s, actor, "contract.term", contract.id, before=before, after=months)


def update_terms(s: Session, contract: Contract, *, devices: int, tolerance_days: int, on_end: str, renew_after_hours: int, auth_validity_days: int,
                 warn_after_days: int | None, suspend_after_days: int | None, note: str | None, actor: str = "fornecedor") -> None:
    """Edita as condições do contrato (valem na próxima validação da instalação). Guarda antes e depois na auditoria."""
    if devices < 0 or tolerance_days < 0 or on_end not in ("stop_inspection", "keep_inspection"):
        raise ServiceError("bad_terms", "máquinas e tolerância não podem ser negativas; escolha uma política de término válida")
    check_terms(renew_after_hours, auth_validity_days, warn_after_days, suspend_after_days)
    fields = dict(max_devices=devices, tolerance_days=tolerance_days, on_end=on_end, renew_after_hours=renew_after_hours,
                  auth_validity_days=auth_validity_days, warn_after_days=warn_after_days, suspend_after_days=suspend_after_days, note=note or None)
    before = {k: getattr(contract, k) for k in fields if k != "note"}
    for k, v in fields.items():
        setattr(contract, k, v)
    audit(s, actor, "contract.terms", contract.id, before=before, after={k: v for k, v in fields.items() if k != "note"})


def unbind(s: Session, contract: Contract, now: datetime, *, actor: str = "fornecedor") -> None:
    """Desvincula a instalação (troca de servidor, recuperação de desastre). Exige um código novo para vincular de novo."""
    inst = _active_installation(s, contract.id)
    if inst is None:
        raise ServiceError("no_installation", "nenhuma instalação vinculada")
    inst.unbound_at = now
    audit(s, actor, "installation.unbind", contract.id, installation=inst.installation_id)


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
                                          validity=timedelta(days=contract.auth_validity_days), renew_after_hours=contract.renew_after_hours,
                                          warn_after_days=contract.warn_after_days, suspend_after_days=contract.suspend_after_days)
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


# ---------------- painel do fornecedor: o que olhar hoje ----------------
LEVEL_OK, LEVEL_WARN, LEVEL_HIGH, LEVEL_CRIT = 0, 1, 2, 3
NEAR_END_DAYS = 30


def silence_overdue(contract: Contract, inst: Installation | None, last_issued_at: datetime | None, now: datetime) -> timedelta | None:
    """Há quanto tempo a validação deveria ter acontecido (negativo = em dia). Mesma conta que a instalação faz com a autorização assinada."""
    if inst is None or contract.status != "ativo":
        return None
    base = last_issued_at or inst.last_seen_at or inst.bound_at
    return now - (base + timedelta(hours=contract.renew_after_hours))


def _days_text(td: timedelta) -> str:
    return f"{max(0, td.days)} dia(s)" if td >= timedelta(days=1) else f"{max(0, int(td.total_seconds() // 3600))} h"


def overview(s: Session, now: datetime) -> list[dict[str, Any]]:
    """Uma linha por contrato, com os alertas que o fornecedor precisa ver (mais graves primeiro)."""
    contracts = s.execute(select(Contract, Customer.name).join(Customer, Customer.id == Contract.customer_id)).all()
    insts = {i.contract_id: i for i in s.execute(select(Installation).where(Installation.unbound_at.is_(None))).scalars()}
    last = {a.contract_id: a for a in s.execute(select(IssuedAuthorization).ext(distinct_on(IssuedAuthorization.contract_id))
                                                .order_by(IssuedAuthorization.contract_id, IssuedAuthorization.serial.desc())).scalars()}
    valid_code = {r[0]: r[1] for r in s.execute(select(ActivationCode.contract_id, func.max(ActivationCode.expires_at))
                                                .where(ActivationCode.used_at.is_(None), ActivationCode.expires_at > now).group_by(ActivationCode.contract_id)).all()}
    out: list[dict[str, Any]] = []
    for k, customer in contracts:
        inst = insts.get(k.id)
        la = last.get(k.id)
        od = silence_overdue(k, inst, la.issued_at if la else None, now)
        alerts: list[tuple[int, str]] = []
        silence = "ok"
        if od is not None and od >= INTERNAL_ALERT_AFTER:
            silence, lvl = "internal", LEVEL_WARN
            txt = f"Sem validar há {_days_text(od)} (a validação era esperada a cada {max(1, k.renew_after_hours // 24)} dia(s)). Só você vê este alerta por enquanto."
            if k.warn_after_days is not None and od >= timedelta(days=k.warn_after_days):
                silence, lvl = "client_warned", LEVEL_HIGH
                txt = f"O CLIENTE JÁ ESTÁ SENDO AVISADO: {_days_text(od)} sem validar."
            if k.suspend_after_days is not None and od >= timedelta(days=k.suspend_after_days):
                silence, lvl = "suspended", LEVEL_CRIT
                txt = f"INSPEÇÃO SUSPENSA NO CLIENTE: {_days_text(od)} sem validar. Volta sozinha na próxima validação."
            alerts.append((lvl, txt))
        dl = days_left(k, now)
        if k.status == "encerrado":
            alerts.append((LEVEL_HIGH, f"Contrato ENCERRADO{': ' + k.close_reason if k.close_reason else ''}"))
        elif dl is not None and dl < 0:
            tol_left = (k.ends_at + timedelta(days=k.tolerance_days) - now).days  # type: ignore[operator]
            alerts.append((LEVEL_CRIT if tol_left < 0 else LEVEL_HIGH, "Contrato VENCIDO" + (f", tolerância por mais {tol_left} dia(s)" if tol_left >= 0 else " e fora da tolerância")))
        elif dl is not None and dl <= NEAR_END_DAYS:
            alerts.append((LEVEL_WARN, f"Vence em {dl} dia(s): hora de renovar"))
        used = inst.last_device_count if inst else None
        if used is not None and k.max_devices and used > k.max_devices:
            alerts.append((LEVEL_WARN, f"{used} máquinas em uso para um limite de {k.max_devices}: proponha o ajuste"))
        if k.status == "pendente" and k.id not in valid_code:
            alerts.append((LEVEL_WARN, "Ainda não ativado e sem código válido: gere um código novo"))
        out.append({"id": k.id, "customer": customer, "status": k.status, "devices_max": k.max_devices, "devices_used": used, "ends_at": k.ends_at,
                    "days_left": dl, "last_seen_at": inst.last_seen_at if inst else None, "last_issued_at": la.issued_at if la else None,
                    "version": inst.product_version if inst else None, "hostname": inst.hostname if inst else None, "has_installation": inst is not None,
                    "overdue": od, "silence": silence, "alerts": sorted(alerts, reverse=True), "level": max((a[0] for a in alerts), default=LEVEL_OK),
                    "code_valid_until": valid_code.get(k.id), "warn_after_days": k.warn_after_days, "suspend_after_days": k.suspend_after_days,
                    "renew_after_hours": k.renew_after_hours})
    out.sort(key=lambda r: (-r["level"], str(r["customer"]).lower()))
    return out


def recent_refusals(s: Session, now: datetime, days: int = 7, limit: int = 30) -> list[dict[str, Any]]:
    """Pedidos recusados (instalação não reconhecida, código inválido, pedido repetido...): o 'não reconheceu' do alerta interno."""
    rows = s.execute(select(AuditEntry).where(AuditEntry.action.like("%.refused"), AuditEntry.at >= now - timedelta(days=days))
                     .order_by(AuditEntry.id.desc()).limit(limit)).scalars()
    return [{"at": e.at, "action": e.action, "code": (e.detail or {}).get("code"), "ip": (e.detail or {}).get("ip")} for e in rows]
