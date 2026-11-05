"""Endpoint dos inference hooks do Claude Enterprise (beta) e a configuração no console. Ver docs/inference-hooks.md."""
from __future__ import annotations

import base64
import binascii
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from promptshield_inference_hooks import SignatureError, parse_frame, verify
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app import audit, crypto, inference_hook
from app.config import settings
from app.db import tenant_session
from app.models import InferenceHookConfig
from app.security import Principal, require_ingest, require_roles

router = APIRouter(prefix="/v1/inference-hook", tags=["inference hooks (Claude Enterprise, beta)"])


def _get_or_create(s, tenant_id: uuid.UUID) -> InferenceHookConfig:
    cfg = s.execute(select(InferenceHookConfig)).scalar_one_or_none()
    if cfg is None:
        cfg = InferenceHookConfig(tenant_id=tenant_id)
        s.add(cfg)
        s.flush()
    return cfg


def _handle(p: Principal, headers: dict[str, str], body: bytes) -> JSONResponse:
    started = time.monotonic()
    with tenant_session(p.tenant_id) as s:
        cfg = _get_or_create(s, p.tenant_id)
        now = datetime.now(timezone.utc)
        try:
            secrets = inference_hook.decrypt_secrets(cfg, now)
            verify(secrets, headers, body)  # sem segredo configurado também falha: nada é aceito sem assinatura
        except (SignatureError, crypto.MasterKeyMissingError) as exc:
            cfg.rejected_count += 1
            cfg.last_rejected_at = now
            msg = "chave mestra não configurada" if isinstance(exc, crypto.MasterKeyMissingError) else str(exc)
            return JSONResponse({"detail": msg}, status_code=status.HTTP_401_UNAUTHORIZED)  # não-200: a Anthropic trata como falha
        try:
            frame = parse_frame(body)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
        request_id = headers.get("webhook-id") or frame.request_id or str(uuid.uuid4())
        verdict = inference_hook.process(s, p, cfg, frame, request_id, started)
        return JSONResponse(verdict, status_code=200)


@router.post("", summary="Recebe um frame assinado da Anthropic (prompt ou tool_call) e devolve allow ou deny")
async def receive(request: Request, p: Annotated[Principal, Depends(require_ingest)]) -> JSONResponse:
    declared = request.headers.get("content-length")
    limit = settings.inference_hook_max_body_bytes
    if declared and declared.isdigit() and int(declared) > limit:
        return JSONResponse({"detail": "corpo grande demais"}, status_code=413)
    body = await request.body()
    if len(body) > limit:
        return JSONResponse({"detail": "corpo grande demais"}, status_code=413)
    headers = {k.lower(): v for k, v in request.headers.items()}
    return await run_in_threadpool(_handle, p, headers, body)


# ---------- configuração (console) ----------
class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["shadow", "enforce"] | None = None
    scope: Literal["full", "latest"] | None = None
    evaluate_tool_calls: bool | None = None


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = Field(min_length=10, max_length=500)


def _view(s, cfg: InferenceHookConfig) -> dict[str, Any]:
    stats = s.execute(text("""
        SELECT count(*) AS requests,
               count(*) FILTER (WHERE outcome = 'deny') AS denied,
               count(*) FILTER (WHERE would_deny AND outcome <> 'deny') AS would_deny,
               count(*) FILTER (WHERE outcome IN ('failure_allow','failure_deny')) AS failures,
               coalesce(sum(skipped_attachments), 0) AS skipped_attachments,
               coalesce(round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::int, 0) AS p95_ms,
               coalesce(max(latency_ms), 0) AS max_ms
        FROM inference_hook_requests WHERE created_at >= now() - interval '24 hours' AND outcome <> 'config_test'""")).mappings().one()
    now = datetime.now(timezone.utc)
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"mode": cfg.mode, "scope": cfg.scope, "evaluate_tool_calls": cfg.evaluate_tool_calls,
            "has_secret": cfg.secret_ciphertext is not None,
            "previous_secret_active": bool(cfg.previous_secret_ciphertext and cfg.previous_expires_at and cfg.previous_expires_at > now),
            "rejected_count": cfg.rejected_count, "last_rejected_at": iso(cfg.last_rejected_at),
            "last_request_at": iso(cfg.last_request_at), "last_test_at": iso(cfg.last_test_at),
            "endpoint_path": "/v1/inference-hook", "budget_ms": settings.inference_hook_budget_ms,
            "integration_status": "parcial", "stats_24h": dict(stats),
            "notice": "Beta da Anthropic (Claude Enterprise). Testado só com requisições simuladas conforme a documentação."}


@router.get("/config", summary="Estado e estatísticas das últimas 24 horas (nunca devolve o segredo)")
def get_config(p: Annotated[Principal, Depends(require_roles("admin", "analista", "auditor"))]) -> dict[str, Any]:
    with tenant_session(p.tenant_id) as s:
        return _view(s, _get_or_create(s, p.tenant_id))


@router.put("/config", summary="Modo (sombra ou aplicar), escopo e validação de chamadas de ferramenta")
def put_config(body: ConfigPatch, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict[str, Any]:
    with tenant_session(p.tenant_id) as s:
        cfg = _get_or_create(s, p.tenant_id)
        before = {"mode": cfg.mode, "scope": cfg.scope, "evaluate_tool_calls": cfg.evaluate_tool_calls}
        data = body.model_dump(exclude_unset=True)
        if data.get("mode") == "enforce" and cfg.secret_ciphertext is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "configure o segredo de assinatura antes de aplicar vereditos")
        for k, v in data.items():
            if v is not None:
                setattr(cfg, k, v)
        cfg.updated_at = datetime.now(timezone.utc)
        s.flush()
        audit.write(s, p, "inference_hook.config", "inference_hook", str(cfg.id), {"before": before, "after": data})
        return _view(s, cfg)


@router.put("/secret", summary="Guarda o segredo de assinatura (whsec_...). Trocar mantém o anterior aceito por alguns minutos")
def put_secret(body: SecretIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict[str, Any]:
    raw = body.secret.strip()
    try:
        key = base64.b64decode(raw[6:] if raw.startswith("whsec_") else raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "segredo inválido: cole o valor whsec_... exatamente como a Anthropic mostrou") from exc
    if len(key) < 16:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "segredo curto demais")
    try:
        blob = crypto.encrypt_secret(p.tenant_id, raw)
    except crypto.MasterKeyMissingError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "chave mestra não configurada: não dá para guardar o segredo") from exc
    with tenant_session(p.tenant_id) as s:
        cfg = _get_or_create(s, p.tenant_id)
        rotated = cfg.secret_ciphertext is not None
        if rotated:
            cfg.previous_secret_ciphertext = cfg.secret_ciphertext
            cfg.previous_expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.inference_hook_previous_secret_minutes)
        cfg.secret_ciphertext = blob
        cfg.updated_at = datetime.now(timezone.utc)
        s.flush()
        audit.write(s, p, "inference_hook.secret", "inference_hook", str(cfg.id), {"rotated": rotated})
        return _view(s, cfg)
