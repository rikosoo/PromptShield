"""Serviço de licenças do fornecedor: clientes, contratos, códigos de ativação, instalações, autorizações emitidas e auditoria."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    __tablename__ = "lic_customers"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = _ts()


class Contract(Base):
    """O direito do cliente ao produto. `status`: pendente (vendido, ainda não ativado), ativo, encerrado.
    O prazo começa na ATIVAÇÃO (starts_at/ends_at são preenchidos nela)."""

    __tablename__ = "lic_contracts"
    __table_args__ = (CheckConstraint("status IN ('pendente','ativo','encerrado')", name="ck_lic_contract_status"),
                      CheckConstraint("on_end IN ('stop_inspection','keep_inspection')", name="ck_lic_contract_on_end"),
                      CheckConstraint("max_devices >= 0 AND term_months > 0 AND tolerance_days >= 0 AND auth_validity_days > 0", name="ck_lic_contract_nums"))
    id: Mapped[uuid.UUID] = _pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lic_customers.id"))
    max_devices: Mapped[int] = mapped_column(Integer)
    term_months: Mapped[int] = mapped_column(Integer)
    tolerance_days: Mapped[int] = mapped_column(Integer, default=15)
    on_end: Mapped[str] = mapped_column(String(20), default="stop_inspection")
    auth_validity_days: Mapped[int] = mapped_column(Integer, default=7)
    renew_after_hours: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(12), default="pendente")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class ActivationCode(Base):
    __tablename__ = "lic_activation_codes"
    id: Mapped[uuid.UUID] = _pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lic_contracts.id"))
    prefix: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_installation: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()


class Installation(Base):
    """Uma instalação do cliente, identificada pela chave pública que ELA gerou. Uma ativa por contrato (`unbound_at` nulo)."""

    __tablename__ = "lic_installations"
    __table_args__ = (Index("uq_lic_one_active_installation", "contract_id", unique=True, postgresql_where="unbound_at IS NULL"),)
    id: Mapped[uuid.UUID] = _pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lic_contracts.id"))
    installation_id: Mapped[str] = mapped_column(String(64), unique=True)
    public_key: Mapped[str] = mapped_column(String(100))
    hostname: Mapped[str | None] = mapped_column(String(200))
    product_version: Mapped[str | None] = mapped_column(String(40))
    bound_at: Mapped[datetime] = _ts()
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_device_count: Mapped[int | None] = mapped_column(Integer)


class IssuedAuthorization(Base):
    __tablename__ = "lic_authorizations"
    __table_args__ = (Index("ix_lic_auth_contract_serial", "contract_id", "serial"),)
    id: Mapped[uuid.UUID] = _pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lic_contracts.id"))
    installation_id: Mapped[str] = mapped_column(String(64))
    serial: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))            # activation | renewal
    status: Mapped[str] = mapped_column(String(8))           # active | closed
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auth_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))


class Nonce(Base):
    """Nonces já vistos (impede repetir um pedido capturado dentro da janela de tempo)."""

    __tablename__ = "lic_nonces"
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    """Só de inserção. `actor`: 'fornecedor' (CLI) ou o identificador da instalação."""

    __tablename__ = "lic_audit"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = _ts()
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    contract_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
