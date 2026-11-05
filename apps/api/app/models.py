import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = _ts()
    store_original: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_mode: Mapped[str] = mapped_column(String(10), default="open")
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    policy_url: Mapped[str | None] = mapped_column(String(500))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    volume_threshold_per_hour: Mapped[int] = mapped_column(Integer, default=60)
    # licença: definida SÓ pelo fornecedor (python -m app.cli set-license); nenhuma rota do administrador da empresa altera
    max_devices: Mapped[int | None] = mapped_column(Integer)
    license_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # suspensão (inadimplência/encerramento): só o fornecedor liga e desliga (python -m app.cli suspend/resume)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(String(200))
    original_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    last_retention_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pilot_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pilot_expected_users: Mapped[int | None] = mapped_column(Integer)
    pilot_days: Mapped[int] = mapped_column(Integer, default=30)
    omit_text_categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["saude"])
    monitored_domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com", "copilot.com"])


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    department: Mapped[str | None] = mapped_column(String(120))
    groups: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["ingest"])
    created_at: Mapped[datetime] = _ts()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    machine_hash: Mapped[str | None] = mapped_column(String(64))
    token_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("enrollment_tokens.id", ondelete="SET NULL"))
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("api_keys.id", ondelete="SET NULL"))
    hostname: Mapped[str] = mapped_column(String(200))
    os: Mapped[str | None] = mapped_column(String(60))
    client_version: Mapped[str | None] = mapped_column(String(40))
    tools: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    ias: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)       # IAs que a pessoa escolheu monitorar nesta máquina (ids do catálogo do sensor)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrolled_at: Mapped[datetime] = _ts()


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    match: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10), default="monitor")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Event(Base):
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = _ts()
    channel: Mapped[str] = mapped_column(String(30))
    app: Mapped[str] = mapped_column(String(80))
    integration_status: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(120))
    device_id: Mapped[str | None] = mapped_column(String(200))
    agent_id: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    session_id: Mapped[str | None] = mapped_column(String(200))
    personal_account: Mapped[bool] = mapped_column(Boolean, default=False)
    tool_name: Mapped[str | None] = mapped_column(String(120))
    masked_text: Mapped[str] = mapped_column(Text)
    text_length: Mapped[int] = mapped_column(Integer)
    original_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)              # chave (sensor) que enviou; nulo em eventos antigos
    attachments: Mapped[list[Any] | None] = mapped_column(JSON)   # nomes já mascarados, tamanho e tipo; nunca o conteúdo


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_pk: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    categories: Mapped[list[Any]] = mapped_column(JSON)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_score: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list[Any]] = mapped_column(JSON)
    spans: Mapped[list[Any]] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(20))
    would_decide: Mapped[str] = mapped_column(String(20))
    policy_hits: Mapped[list[Any]] = mapped_column(JSON)
    score_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = _ts()


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_pk: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="aberto")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class EventFeedback(Base):
    """Revisão humana de UMA análise. Vale a última revisão (o histórico fica na auditoria)."""
    __tablename__ = "event_feedback"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_pk: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    verdict: Mapped[str] = mapped_column(String(20))
    wrong_categories: Mapped[list[Any]] = mapped_column(JSON, default=list)
    missing_categories: Mapped[list[Any]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class LicenseRecord(Base):
    """Estado da licença desta INSTALAÇÃO (uma linha). Sem tenant e sem RLS: vale para o servidor inteiro."""
    __tablename__ = "license_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    installation_id: Mapped[str] = mapped_column(String(64))
    auth_token: Mapped[str | None] = mapped_column(Text)
    serial: Mapped[int] = mapped_column(Integer, default=0)
    high_water: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))        # maior horário já visto: protege contra relógio voltado
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_failed: Mapped[bool] = mapped_column(Boolean, default=False)           # falha de COMUNICAÇÃO (rede, 5xx, 429)
    last_error: Mapped[str | None] = mapped_column(String(300))                         # inclui recusas do fornecedor (contrato vencido...)
    updated_at: Mapped[datetime] = _ts()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = _tenant()
    at: Mapped[datetime] = _ts()
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    target: Mapped[str] = mapped_column(String(1000))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    target_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    rule: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    dedup_key: Mapped[str] = mapped_column(String(300))
    user_id: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(120))
    event_pk: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("events.id", ondelete="SET NULL"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("incidents.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = _ts()
    last_seen: Mapped[datetime] = _ts()


class OutboxItem(Base):
    __tablename__ = "notification_outbox"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    channel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("notification_channels.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    ref_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = _ts()
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _ts()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(5))
    frequency: Mapped[str] = mapped_column(String(10))
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_period_end: Mapped[Any | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _ts()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(5))
    period_start: Mapped[Any] = mapped_column(Date)
    period_end: Mapped[Any] = mapped_column(Date)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(200))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("report_schedules.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()


class InferenceHookConfig(Base):
    __tablename__ = "inference_hook_configs"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    mode: Mapped[str] = mapped_column(String(10), default="shadow")
    scope: Mapped[str] = mapped_column(String(10), default="full")
    evaluate_tool_calls: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    last_rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class InferenceHookRequest(Base):
    __tablename__ = "inference_hook_requests"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    request_id: Mapped[str] = mapped_column(String(200))
    frame_type: Mapped[str] = mapped_column(String(40))
    application: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(20))
    would_deny: Mapped[bool] = mapped_column(Boolean, default=False)
    blocks_total: Mapped[int] = mapped_column(Integer, default=0)
    blocks_new: Mapped[int] = mapped_column(Integer, default=0)
    skipped_attachments: Mapped[int] = mapped_column(Integer, default=0)
    categories: Mapped[list[Any]] = mapped_column(JSON, default=list)
    reference_id: Mapped[str | None] = mapped_column(String(50))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _ts()


class PilotReview(Base):
    __tablename__ = "pilot_reviews"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    event_pk: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"))
    sample_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    label: Mapped[str | None] = mapped_column(String(20))
    reviewer_id: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
