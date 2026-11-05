"""Matrícula de dispositivos: o administrador cria um token (revogável, com validade e limite de usos); cada máquina troca o token por
uma chave de API PRÓPRIA. Assim um instalador vazado não permite falsificar eventos em nome da empresa por tempo indeterminado, e dá
para revogar uma máquina só. Integração REAL só depois de testada em máquinas reais (docs/implantacao-empresa.md)."""
from __future__ import annotations

import csv
import hashlib
import io
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from app import audit, audit_system, license, ratelimit
from app.config import settings
from app.csvsafe import csv_safe
from app.db import anonymous_session, tenant_session
from app.models import ApiKey, Device, EnrollmentToken, Event, Tenant
from app.security import READ_ROLES, Principal, generate_api_key, require_ingest, require_roles

router = APIRouter(prefix="/v1", tags=["matrícula de dispositivos"])
TOKEN_PREFIX = "pse_"  # noqa: S105 - prefixo público do formato do token, não é segredo


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int = Field(default=14, ge=1, le=90)
    max_uses: int | None = Field(default=1000, ge=1, le=100000)


class EnrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200)
    hostname: str = Field(min_length=1, max_length=200)
    os: str | None = Field(default=None, max_length=60)
    client_version: str | None = Field(default=None, max_length=40)
    tools: list[str] = Field(default_factory=list, max_length=20)
    ias: list[Annotated[str, Field(pattern=r"^[a-z0-9_]{2,40}$")]] = Field(default_factory=list, max_length=20)   # IAs escolhidas (ids do catálogo do sensor)
    # SHA-256 de um identificador da máquina (MachineGuid, machine-id, IOPlatformUUID): reinstalar na mesma máquina reaproveita a vaga
    machine_id_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@router.post("/enrollment-tokens", status_code=201, summary="Cria token de matrícula; o valor aparece só nesta resposta")
def create_token(body: TokenIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    prefix = secrets.token_hex(4)
    token = f"{TOKEN_PREFIX}{prefix}_{secrets.token_urlsafe(24)}"
    with tenant_session(p.tenant_id) as s:
        t = EnrollmentToken(tenant_id=p.tenant_id, name=body.name, prefix=f"{TOKEN_PREFIX}{prefix}", token_hash=_hash(token),
                            expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days), max_uses=body.max_uses)
        s.add(t)
        s.flush()
        audit.write(s, p, "enrollment_token.create", "enrollment_token", str(t.id),
                    {"name": body.name, "expires_in_days": body.expires_in_days, "max_uses": body.max_uses})
        return {"id": str(t.id), "name": t.name, "prefix": t.prefix, "token": token, "expires_at": t.expires_at.isoformat(), "max_uses": t.max_uses}


def _token_view(t: EnrollmentToken, now: datetime) -> dict:
    status_ = "revogado" if t.revoked_at else "expirado" if t.expires_at <= now else "esgotado" if t.max_uses is not None and t.uses >= t.max_uses else "ativo"
    return {"id": str(t.id), "name": t.name, "prefix": t.prefix, "status": status_, "uses": t.uses, "max_uses": t.max_uses,
            "expires_at": t.expires_at.isoformat(), "created_at": t.created_at.isoformat()}


@router.get("/enrollment-tokens")
def list_tokens(p: Annotated[Principal, Depends(require_roles("admin"))]) -> list[dict]:
    now = datetime.now(timezone.utc)
    with tenant_session(p.tenant_id) as s:
        return [_token_view(t, now) for t in s.scalars(select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc()))]


@router.post("/enrollment-tokens/{token_id}/revoke")
def revoke_token(token_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        t = s.get(EnrollmentToken, token_id)
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token não encontrado")
        t.revoked_at = t.revoked_at or datetime.now(timezone.utc)
        audit.write(s, p, "enrollment_token.revoke", "enrollment_token", str(t.id), {"name": t.name})
        return _token_view(t, datetime.now(timezone.utc))


@router.post("/enroll", status_code=201, summary="Troca um token de matrícula por uma chave de API própria da máquina (sem login)")
def enroll(body: EnrollIn, request: Request) -> dict:
    wait = ratelimit.check(f"enroll:{request.client.host if request.client else '?'}", settings.rate_limit_enroll_per_minute)
    if wait is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "muitas tentativas", headers={"Retry-After": str(wait)})
    refused: license.Refused | None = None
    out: dict | None = None
    tenant_id = None
    try:
        # UMA transação: consumir o token, travar o tenant, conferir a licença e criar a máquina. Recusa = tudo desfeito (o token não é gasto).
        with anonymous_session() as s:
            row = s.execute(text("SELECT token_id, tenant_id FROM enroll_consume(:h)"), {"h": _hash(body.token)}).first()
            if row is None:  # token inexistente, expirado, revogado ou esgotado: a mesma resposta para não ajudar quem adivinha
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token de matrícula inválido")
            tenant_id = row.tenant_id
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            tenant = s.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).scalar_one()   # serializa matrículas em massa
            now = datetime.now(timezone.utc)
            if body.machine_id_hash:   # reinstalação na mesma máquina: libera a vaga antiga antes de contar
                for old in s.scalars(select(Device).where(Device.machine_hash == body.machine_id_hash, Device.revoked_at.is_(None))):
                    old.revoked_at = now
                    k_old = s.get(ApiKey, old.api_key_id) if old.api_key_id else None
                    if k_old is not None:
                        k_old.revoked_at = k_old.revoked_at or now
                s.flush()
            license.check_new_seat(s, tenant, now)
            key, prefix, digest = generate_api_key()
            k = ApiKey(tenant_id=tenant_id, name=f"dispositivo:{body.hostname}"[:120], prefix=prefix, key_hash=digest, scopes=["ingest"])
            s.add(k)
            s.flush()
            d = Device(tenant_id=tenant_id, token_id=row.token_id, api_key_id=k.id, hostname=body.hostname, os=body.os,
                       client_version=body.client_version, tools=sorted(set(body.tools)), ias=sorted(set(body.ias)), machine_hash=body.machine_id_hash)
            s.add(d)
            s.flush()
            audit_system.write(s, tenant_id, "device.enroll", "device", str(d.id), {"hostname": body.hostname, "tools": d.tools, "ias": d.ias})
            out = {"device_id": str(d.id), "api_key": key}
    except license.Refused as exc:
        refused = exc
    if refused is not None:
        with tenant_session(tenant_id) as s2:
            audit_system.write(s2, tenant_id, "device.enroll_refused", "device", None, {"hostname": body.hostname, "reason": refused.reason})
        raise HTTPException(status.HTTP_403_FORBIDDEN, refused.detail)
    assert out is not None
    return out


def _activity(s, key_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, dict[str, dict]]:
    """Por sensor (chave), de quais apps chegaram eventos nos últimos 30 dias: evidência REAL de que a IA está sendo capturada."""
    if not key_ids:
        return {}
    since7 = now - timedelta(days=7)
    rows = s.execute(select(Event.api_key_id, Event.app, func.count().label("n30"), func.count().filter(Event.occurred_at >= since7).label("n7"),
                            func.max(Event.occurred_at).label("last"))
                     .where(Event.api_key_id.in_(key_ids), Event.occurred_at >= now - timedelta(days=30))
                     .group_by(Event.api_key_id, Event.app)).all()
    out: dict[uuid.UUID, dict[str, dict]] = {}
    for kid, app, n30, n7, last in rows:
        out.setdefault(kid, {})[app] = {"events_7d": int(n7), "events_30d": int(n30), "last_at": last.isoformat()}
    return out


def _last_users(s, key_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, dict]:
    """Quem usou cada máquina por último e quantas pessoas diferentes nos últimos 30 dias (máquina compartilhada aparece com mais de uma)."""
    if not key_ids:
        return {}
    since = now - timedelta(days=30)
    last = s.execute(select(Event.api_key_id, Event.user_id, Event.department, Event.occurred_at)
                     .where(Event.api_key_id.in_(key_ids), Event.occurred_at >= since)
                     .distinct(Event.api_key_id).order_by(Event.api_key_id, Event.occurred_at.desc())).all()
    counts = dict(s.execute(select(Event.api_key_id, func.count(func.distinct(Event.user_id)))
                            .where(Event.api_key_id.in_(key_ids), Event.occurred_at >= since).group_by(Event.api_key_id)).all())
    return {kid: {"last_user": user, "last_department": dept, "last_user_at": at.isoformat(), "users_30d": int(counts.get(kid, 1))}
            for kid, user, dept, at in last}


def sensor_status(revoked: bool, last_seen_at: str | None, now: datetime) -> str:
    """Mesma regra do console (lib/sensors.ts): ativo até 24 h, sem atividade até 7 dias, inativo depois. O sensor só fala quando alguém usa uma IA."""
    if revoked:
        return "revogado"
    if not last_seen_at:
        return "nunca"
    age = now - datetime.fromisoformat(last_seen_at)
    return "ativo" if age <= timedelta(hours=24) else "quieto" if age <= timedelta(days=7) else "inativo"


def _device_view(d: Device, k: ApiKey | None, activity: dict[str, dict] | None = None, who: dict | None = None) -> dict:
    last = k.last_used_at if k else None
    ref = max(x for x in (last, d.enrolled_at) if x is not None)
    return {"counts_toward_license": d.revoked_at is None and ref >= license.cutoff(), "id": str(d.id), "hostname": d.hostname, "os": d.os, "client_version": d.client_version, "tools": d.tools, "ias": list(d.ias or []), "activity": activity or {},
            "last_user": (who or {}).get("last_user"), "last_department": (who or {}).get("last_department"),
            "last_user_at": (who or {}).get("last_user_at"), "users_30d": (who or {}).get("users_30d", 0),
            "enrolled_at": d.enrolled_at.isoformat(), "last_seen_at": last.isoformat() if last else None,
            "revoked": d.revoked_at is not None}


@router.get("/devices", summary="Máquinas matriculadas e cobertura por ferramenta")
def list_devices(p: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(Device, ApiKey).outerjoin(ApiKey, ApiKey.id == Device.api_key_id).order_by(Device.enrolled_at.desc())).all()
        now = datetime.now(timezone.utc)
        key_ids = [d.api_key_id for d, _ in rows if d.api_key_id]
        acts, users = _activity(s, key_ids, now), _last_users(s, key_ids, now)
        devices = [_device_view(d, k, acts.get(d.api_key_id), users.get(d.api_key_id)) for d, k in rows]
        lic = license.summary(s, s.get(Tenant, p.tenant_id))
    active = [d for d in devices if not d["revoked"]]
    coverage: dict[str, int] = {}
    ias_coverage: dict[str, int] = {}
    for d in active:
        for t in d["tools"]:
            coverage[t] = coverage.get(t, 0) + 1
        for i in d["ias"]:
            ias_coverage[i] = ias_coverage.get(i, 0) + 1
    return {"devices": devices, "active": len(active), "coverage": coverage, "ias_coverage": ias_coverage, "license": lic}


CAPTURE_APPS = {"chatgpt_web", "copilot_web", "gemini_web", "claude_web", "claude_code", "github_copilot_cli", "codex_cli"}   # IAs cujo id é o `source.app` dos eventos


@router.get("/devices/export.csv", response_class=Response, summary="Exporta os sensores em CSV (mesmos filtros do painel); a exportação é auditada")
def export_devices(p: Annotated[Principal, Depends(require_roles("admin", "auditor"))], q: Annotated[str | None, Query(max_length=100)] = None,
                   ia: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{2,40}$")] = None,
                   situacao: Annotated[str | None, Query(pattern="^(ativo|quieto|inativo|nunca|revogado)$")] = None) -> Response:
    with tenant_session(p.tenant_id) as s:
        rows = s.execute(select(Device, ApiKey).outerjoin(ApiKey, ApiKey.id == Device.api_key_id)).all()
        now = datetime.now(timezone.utc)
        key_ids = [d.api_key_id for d, _ in rows if d.api_key_id]
        acts, users = _activity(s, key_ids, now), _last_users(s, key_ids, now)
        views = [_device_view(d, k, acts.get(d.api_key_id), users.get(d.api_key_id)) for d, k in rows]
        wanted = (q or "").strip().casefold()
        out = []
        for v in sorted(views, key=lambda x: x["hostname"].casefold()):
            st = sensor_status(v["revoked"], v["last_seen_at"], now)
            if (wanted and wanted not in v["hostname"].casefold()) or (ia and ia not in v["ias"]) or (situacao and st != situacao):
                continue
            out.append((v, st))
        audit.write(s, p, "export.sensors_csv", "devices", None, {"filters": {k: x for k, x in (("q", q), ("ia", ia), ("situacao", situacao)) if x}, "rows": len(out)})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["maquina", "sistema", "versao_sensor", "situacao", "matriculada_em", "ultimo_envio", "ultimo_usuario", "usuarios_30d", "ias_habilitadas",
                "ias_capturando_7d", "mecanismos", "ocupa_vaga"])
    for v, st in out:
        capturing = [i for i in v["ias"] if i in CAPTURE_APPS and v["activity"].get(i, {}).get("events_7d", 0) > 0]
        w.writerow([csv_safe(v["hostname"]), csv_safe(v["os"]), csv_safe(v["client_version"]), st, v["enrolled_at"], v["last_seen_at"] or "",
                    csv_safe(v["last_user"]), v["users_30d"], ";".join(v["ias"]), ";".join(capturing), ";".join(v["tools"]),
                    "sim" if v.get("counts_toward_license") else "nao"])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="sensores.csv"'})


class IasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ias: list[Annotated[str, Field(pattern=r"^[a-z0-9_]{2,40}$")]] = Field(max_length=20)
    mode: Literal["set", "add"] = "set"          # add: o assistente pode rodar várias vezes e as escolhas se acumulam


@router.put("/device/ias", summary="O sensor informa quais IAs foram escolhidas nesta máquina (a chave identifica a máquina)")
def set_device_ias(body: IasIn, p: Annotated[Principal, Depends(require_ingest)]) -> dict:
    with tenant_session(p.tenant_id) as s:
        d = s.execute(select(Device).where(Device.api_key_id == uuid.UUID(p.id), Device.revoked_at.is_(None))).scalar()
        if d is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "esta chave não pertence a uma máquina matriculada")
        d.ias = sorted(set(d.ias or []) | set(body.ias)) if body.mode == "add" else sorted(set(body.ias))
        audit_system.write(s, p.tenant_id, "device.ias_update", "device", str(d.id), {"ias": d.ias, "mode": body.mode}, actor_id=f"device:{d.id}")
        return {"ias": d.ias}


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    with tenant_session(p.tenant_id) as s:
        d = s.get(Device, device_id)
        if d is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dispositivo não encontrado")
        now = datetime.now(timezone.utc)
        d.revoked_at = d.revoked_at or now
        k = s.get(ApiKey, d.api_key_id) if d.api_key_id else None
        if k is not None:
            k.revoked_at = k.revoked_at or now
        audit.write(s, p, "device.revoke", "device", str(d.id), {"hostname": d.hostname})
        return _device_view(d, k)
