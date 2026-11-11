"""API pública do serviço de licenças: ativação e renovação (pedidos assinados pela instalação) e a chave pública do fornecedor."""
from __future__ import annotations

import threading
import time
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from promptshield_licensing import SignatureError, fingerprint, load_private_key, public_key_b64
from pydantic import BaseModel, Field

from lic_service import panel, service
from lic_service.config import settings
from lic_service.db import session_scope

app = FastAPI(title="PromptShield, serviço de licenças", version=settings.version)

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def _limited(ip: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        recent = [t for t in _hits.get(ip, []) if now - t < 60]
        recent.append(now)
        _hits[ip] = recent
        if len(_hits) > 10_000:
            _hits.clear()
        return len(recent) > settings.rate_limit_per_minute > 0


def reset_limits() -> None:
    with _lock:
        _hits.clear()


def _key():
    if not settings.license_signing_key:
        raise HTTPException(503, "serviço sem chave de assinatura (LICENSE_SIGNING_KEY)")
    try:
        return load_private_key(settings.license_signing_key)
    except SignatureError as exc:
        raise HTTPException(503, "chave de assinatura ilegível") from exc


class SignedRequest(BaseModel):
    request: Annotated[str, Field(min_length=20, max_length=4000)]


app.include_router(panel.router)      # /painel: responde 404 enquanto PANEL_ENABLED não estiver ligado


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/public-key", summary="Chave pública do fornecedor (a instalação do cliente a FIXA; nunca confie numa chave baixada em outro lugar)")
def public_key() -> dict[str, str]:
    k = _key()
    return {"public_key": public_key_b64(k), "key_id": fingerprint(public_key_b64(k))}


def _handle(fn, body: SignedRequest, request: Request, action: str) -> JSONResponse:
    ip = request.client.host if request.client else "?"
    if _limited(ip):
        raise HTTPException(429, "muitos pedidos", headers={"Retry-After": "60"})
    key = _key()
    try:
        with session_scope() as s:
            token = fn(s, key, body.request, service.utcnow())
        return JSONResponse({"authorization": token}, headers={"Cache-Control": "no-store"})
    except service.ServiceError as exc:
        with session_scope() as s:
            service.record_refusal(s, f"{action}.refused", exc.code, ip=ip)
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.http, headers={"Cache-Control": "no-store"})


@app.post("/v1/activate", summary="Troca o código de ativação (de uso único) por uma autorização assinada, vinculando o contrato à instalação")
def activate(body: SignedRequest, request: Request) -> JSONResponse:
    return _handle(service.activate, body, request, "activate")


@app.post("/v1/renew", summary="Validação periódica: devolve outra autorização (e, se houver, os avisos assinados de versão nova) enquanto o contrato permitir")
def renew(body: SignedRequest, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "?"
    if _limited(ip):
        raise HTTPException(429, "muitos pedidos", headers={"Retry-After": "60"})
    key = _key()
    try:
        with session_scope() as s:
            payload = service.renew_with_notices(s, key, body.request, service.utcnow())
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except service.ServiceError as exc:
        with session_scope() as s:
            service.record_refusal(s, "renew.refused", exc.code, ip=ip)
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.http, headers={"Cache-Control": "no-store"})


@app.post("/v1/releases/download", summary="Baixa uma versão publicada (pedido assinado pela instalação; só contrato ativo)")
def download_release(body: SignedRequest, request: Request) -> Response:
    ip = request.client.host if request.client else "?"
    if _limited(ip):
        raise HTTPException(429, "muitos pedidos", headers={"Retry-After": "60"})
    try:
        with session_scope() as s:
            rel, path = service.authorize_download(s, body.request, service.utcnow())
            name, sha = rel.file_name, rel.sha256
        return FileResponse(path, media_type="application/octet-stream", filename=name, headers={"Cache-Control": "no-store", "X-Content-SHA256": sha})
    except service.ServiceError as exc:
        with session_scope() as s:
            service.record_refusal(s, "download.refused", exc.code, ip=ip)
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.http, headers={"Cache-Control": "no-store"})
