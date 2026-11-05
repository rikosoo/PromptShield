from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Channel = Literal["browser", "agent_hook", "api_proxy", "inference_hook"]
Integration = Literal["real", "partial", "experimental"]
Kind = Literal["prompt", "response", "tool_call", "tool_result", "file_upload"]
Action = Literal["allow", "mask", "block", "ask_justification", "alert"]


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _one_line(v: str | None) -> str | None:
    """Rótulos (pessoa, departamento, app, sessão...) viram linha única: quebra de linha ali forja linha de log, de CEF/syslog e de e-mail."""
    t = None if v is None else _CONTROL.sub(" ", v).strip()
    return t or None


def _required_one_line(v: str) -> str:
    t = _one_line(v)
    if not t:
        raise ValueError("não pode ficar vazio nem ter só caracteres de controle")
    return t


class Source(BaseModel):
    channel: Channel
    app: str = Field(min_length=1, max_length=80)
    integration_status: Integration
    _clean = field_validator("app")(_required_one_line)


class Actor(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    device_id: str | None = Field(default=None, max_length=200)
    agent_id: str | None = Field(default=None, max_length=200)
    groups: list[str] = Field(default_factory=list, max_length=50)  # extensão ao evento universal: escopo de política por grupo
    _clean = field_validator("department", "device_id", "agent_id")(_one_line)
    _clean_id = field_validator("user_id")(_required_one_line)


class Attachment(BaseModel):
    """Arquivo anexado pelo usuário: só nome, tamanho e tipo. O conteúdo do arquivo nunca é enviado."""
    name: str = Field(min_length=1, max_length=255)
    size: int | None = Field(default=None, ge=0)
    mime: str | None = Field(default=None, max_length=100)
    _clean = field_validator("name")(lambda v: _required_one_line(v))
    _clean_mime = field_validator("mime")(_one_line)


class Content(BaseModel):
    text: str | None = None
    tool_name: str | None = Field(default=None, max_length=120)
    tool_input: dict[str, Any] | None = None
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)


class Context(BaseModel):
    session_id: str | None = Field(default=None, max_length=200)
    personal_account: bool = False
    _clean = field_validator("session_id")(_one_line)


class EventIn(BaseModel):
    """Evento universal (CLAUDE.md). `tenant_id`, se enviado, precisa coincidir com o da chave."""

    model_config = ConfigDict(extra="forbid")
    event_id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    occurred_at: datetime
    source: Source
    actor: Actor
    kind: Kind
    content: Content
    context: Context = Field(default_factory=Context)


class SpanOut(BaseModel):
    start: int
    end: int
    type: str
    masked: str


class EventResult(BaseModel):
    event_id: uuid.UUID
    decision: Action
    would_decide: Action
    enforced: bool
    masked_text: str
    categories: list[dict[str, Any]]
    flags: dict[str, Any]
    risk: dict[str, Any]
    spans: list[SpanOut]
    policy_hits: list[dict[str, str]]
    incident_id: uuid.UUID | None = None
    duplicate: bool = False


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    enabled: bool = True
    scope: dict[str, list[str]] = Field(default_factory=dict)
    match: dict[str, Any] = Field(default_factory=dict)
    action: Action
    mode: Literal["monitor", "enforce"] = "monitor"  # padrão seguro


class PolicyOut(PolicyIn):
    id: uuid.UUID
    version: int
    updated_at: datetime


class IncidentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["aberto", "em analise", "resolvido", "falso positivo"] | None = None
    assignee_id: uuid.UUID | None = None


class OriginalRequest(BaseModel):
    justification: str = Field(min_length=10, max_length=1000)


class UserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = None
    role: Literal["admin", "analista", "auditor", "leitura"]
    department: str | None = None
    groups: list[str] = Field(default_factory=list)


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=730)


class ApiKeyRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grace_hours: int = Field(default=24, ge=0, le=168)  # por quanto tempo a chave antiga continua valendo; 0 = revoga já


class TenantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_mode: Literal["open", "closed"] | None = None
    retention_days: int | None = Field(default=None, ge=7, le=365)
    original_retention_days: int | None = Field(default=None, ge=1, le=365)
    omit_text_categories: list[str] | None = Field(default=None, max_length=30)
    store_original: bool | None = None
    volume_threshold_per_hour: int | None = Field(default=None, ge=0, le=100000)
    policy_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    monitored_domains: list[str] | None = Field(default=None, max_length=50)

    @field_validator("omit_text_categories")
    @classmethod
    def _omit(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        from promptshield_detection.taxonomy import load as load_taxonomy

        known = set(load_taxonomy())
        bad = [c for c in v if c not in known]
        if bad:
            raise ValueError(f"categoria desconhecida: {bad[0]}")
        return sorted(set(v))

    @field_validator("monitored_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for d in v:
            d = d.strip().lower()
            if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", d):
                raise ValueError(f"domínio inválido: {d!r} (use só o nome, sem https:// nem caminho)")
            out.append(d)
        return out


class FeedbackIn(BaseModel):
    """Revisão humana da análise de um evento. As categorias são ids da taxonomia (validadas na rota)."""
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["correta", "falso_positivo", "faltou"]
    wrong_categories: list[str] = Field(default_factory=list, max_length=30)
    missing_categories: list[str] = Field(default_factory=list, max_length=30)
    note: str | None = Field(default=None, max_length=500)


class JustificationIn(BaseModel):
    justification: str = Field(min_length=10, max_length=1000)


class ChannelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["webhook", "slack", "teams", "email", "syslog_cef", "siem_webhook"]
    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=3, max_length=1000)
    enabled: bool = True
    min_severity: Literal["baixo", "medio", "alto", "critico"] | None = None  # canais de alerta
    min_score: int | None = Field(default=None, ge=0, le=100)  # canais de eventos (SIEM)
    proto: Literal["udp", "tcp"] | None = None  # syslog
    secret: str | None = Field(default=None, min_length=16, max_length=200)  # chave HMAC do webhook


class ChannelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_severity: Literal["baixo", "medio", "alto", "critico"] | None = None
    min_score: int | None = Field(default=None, ge=0, le=100)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["executivo", "lgpd", "piloto"]
    format: Literal["pdf", "csv"]
    start: date
    end: date


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["executivo", "lgpd", "piloto"]
    format: Literal["pdf", "csv"]
    frequency: Literal["mensal", "semanal"]
    recipients: list[str] = Field(default_factory=list, max_length=20)
