"""Licenciamento on-premise, lado do cliente: identidade da instalação, ativação, renovação periódica e o estado da licença.

O servidor do cliente NÃO decide nada sozinho: ele guarda a autorização assinada pelo fornecedor (chave pública FIXADA na instalação), confere a
assinatura e o vínculo com a própria chave, e interpreta o resultado com as regras públicas de `promptshield_licensing.states`.
Com LICENSE_MODE=off (padrão) nada disto é consultado. Ver docs/licenciamento.md."""
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from promptshield_licensing import (
    Authorization,
    AuthorizationError,
    Installation,
    LicenseState,
    SignatureError,
    State,
    build_request,
    evaluate,
    load_private_key,
    load_public_key,
    verify_authorization,
)
from sqlalchemy import select, text

from app.config import settings
from app.db import anonymous_session
from app.models import LicenseRecord

ACTIVE_WINDOW_DAYS = 45
HIGH_WATER_STEP = timedelta(minutes=5)
CACHE_SECONDS = 10.0


class LicenseError(Exception):
    """Falha de ativação/renovação. `code` vem do serviço de licenças (ou: unreachable, bad_authorization, not_configured, not_activated)."""

    def __init__(self, code: str, detail: str, http: int = 400) -> None:
        super().__init__(detail)
        self.code, self.detail, self.http = code, detail, http


def _now() -> datetime:
    return datetime.now(timezone.utc)


def http_factory() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False)


def enabled() -> bool:
    return settings.license_mode == "onprem"


# ---------- identidade da instalação (a chave privada nunca sai desta máquina) ----------
_inst_lock = threading.Lock()


def _key_path() -> Path:
    return Path(settings.license_state_dir) / "installation.pem"


def installation(create: bool = True) -> Installation | None:
    path = _key_path()
    with _inst_lock:
        for _ in range(20):
            if path.exists() and path.stat().st_size > 0:
                return Installation(load_private_key(path.read_bytes()))
            if not create:
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)   # exclusivo: api e worker não criam duas chaves
            except FileExistsError:
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "wb") as f:
                f.write(Installation.create().pem())
        raise LicenseError("no_identity", "não foi possível criar a identidade da instalação (verifique LICENSE_STATE_DIR)", 500)


def _pinned() -> object:
    if not settings.license_public_key:
        raise LicenseError("not_configured", "LICENSE_PUBLIC_KEY não configurada: sem a chave pública do fornecedor não há como validar a licença", 503)
    try:
        return load_public_key(settings.license_public_key)
    except SignatureError as exc:
        raise LicenseError("not_configured", "LICENSE_PUBLIC_KEY ilegível", 503) from exc


def _server_url() -> str:
    url = (settings.license_server_url or "").rstrip("/")
    if not url:
        raise LicenseError("not_configured", "LICENSE_SERVER_URL não configurada", 503)
    u = urlparse(url)
    if u.scheme != "https" and not settings.license_allow_http:
        raise LicenseError("not_configured", "LICENSE_SERVER_URL precisa ser https", 503)
    return url


# ---------- estado ----------
@dataclass(frozen=True)
class Snapshot:
    state: LicenseState
    auth: Authorization | None
    record: LicenseRecord | None
    problem: str | None = None


def _load(s) -> LicenseRecord | None:
    return s.execute(select(LicenseRecord).where(LicenseRecord.id == 1)).scalar()


def snapshot(now: datetime | None = None) -> Snapshot:
    now = now or _now()
    with anonymous_session() as s:
        rec = _load(s)
        if rec is not None:
            s.expunge(rec)
    if rec is None or not rec.auth_token:
        return Snapshot(evaluate(None, now), None, rec)
    eff = max(now, rec.high_water) if rec.high_water else now        # relógio voltado: vale o maior horário já visto
    inst = installation(create=False)
    try:
        if inst is None:
            raise AuthorizationError("a identidade desta instalação não foi encontrada (LICENSE_STATE_DIR)")
        auth = verify_authorization(rec.auth_token, _pinned(), inst.installation_id, eff)    # type: ignore[arg-type]
    except (AuthorizationError, LicenseError) as exc:
        problem = f"Autorização local inválida: {exc}. Ative de novo com um código do fornecedor."
        return Snapshot(LicenseState(State.NAO_ATIVADO, False, False, problem), None, rec, problem)
    return Snapshot(evaluate(auth, eff, last_success=rec.last_success_at, last_attempt_failed=rec.last_attempt_failed), auth, rec)


_cache: tuple[float, LicenseState] | None = None
_cache_lock = threading.Lock()


def invalidate() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def state(now: datetime | None = None) -> LicenseState:
    """Estado atual. Com relógio explícito (testes) não usa cache. Sem relógio: cache curto e atualização do maior horário visto."""
    global _cache
    if now is not None:
        return snapshot(now).state
    with _cache_lock:
        if _cache and time.monotonic() < _cache[0]:
            return _cache[1]
    now = _now()
    snap = snapshot(now)
    if snap.record is not None and (snap.record.high_water is None or now > snap.record.high_water + HIGH_WATER_STEP):
        _touch(now)
    with _cache_lock:
        _cache = (time.monotonic() + CACHE_SECONDS, snap.state)
    return snap.state


def _touch(now: datetime) -> None:
    with anonymous_session() as s:
        rec = _load(s)
        if rec is not None and (rec.high_water is None or now > rec.high_water):
            rec.high_water = now


# ---------- conversa com o serviço de licenças ----------
def _post(path: str, request: str) -> str:
    url = _server_url() + path
    try:
        with http_factory() as c:
            r = c.post(url, json={"request": request})
    except httpx.HTTPError as exc:
        raise LicenseError("unreachable", "não foi possível falar com o serviço de licenças", 502) from exc
    if r.status_code == 200:
        try:
            return str(r.json()["authorization"])
        except (ValueError, KeyError, TypeError) as exc:
            raise LicenseError("bad_response", "resposta inesperada do serviço de licenças", 502) from exc
    if r.status_code == 429 or r.status_code >= 500:
        raise LicenseError("unreachable", f"serviço de licenças indisponível ({r.status_code})", 502)
    try:
        body = r.json()
        raise LicenseError(str(body.get("code", "refused")), str(body.get("detail", "recusado")), r.status_code)
    except ValueError as exc:
        raise LicenseError("refused", "recusado pelo serviço de licenças", r.status_code) from exc


def _accept(token: str, inst: Installation, rec: LicenseRecord | None, now: datetime) -> Authorization:
    try:
        return verify_authorization(token, _pinned(), inst.installation_id, now, min_serial=rec.serial if rec else 0)    # type: ignore[arg-type]
    except AuthorizationError as exc:
        raise LicenseError("bad_authorization", f"autorização recusada: {exc}", 502) from exc


def _store(token: str, auth: Authorization, inst: Installation, now: datetime) -> None:
    with anonymous_session() as s:
        rec = _load(s)
        if rec is None:
            rec = LicenseRecord(id=1, installation_id=inst.installation_id, activated_at=now)
            s.add(rec)
        rec.installation_id, rec.auth_token, rec.serial = inst.installation_id, token, auth.serial
        rec.last_success_at = rec.last_attempt_at = now
        rec.last_attempt_failed, rec.last_error = False, None
        rec.high_water = max(now, rec.high_water) if rec.high_water else now
        rec.activated_at = rec.activated_at or now
    invalidate()


def _fail(now: datetime, err: LicenseError) -> None:
    with anonymous_session() as s:
        rec = _load(s)
        if rec is not None:
            rec.last_attempt_at = now
            rec.last_attempt_failed = err.code in ("unreachable", "bad_response")          # falha de comunicação conta como "sem contato"; recusa não
            rec.last_error = f"{err.code}: {err.detail}"[:300]
    invalidate()


def activate(code: str, now: datetime | None = None) -> LicenseState:
    now = now or _now()
    _pinned()
    _server_url()
    inst = installation(create=True)
    assert inst is not None
    req = build_request(inst, "activate", now, code=code.strip(), hostname=socket.gethostname()[:200], version=settings.version)
    token = _post("/v1/activate", req)
    with anonymous_session() as s:
        rec = _load(s)
        if rec is not None:
            s.expunge(rec)
    auth = _accept(token, inst, rec, now)
    _store(token, auth, inst, now)
    return state(now)


def active_devices(now: datetime) -> int:
    with anonymous_session() as s:
        return int(s.execute(text("SELECT count_active_devices_all(:c)"), {"c": now - timedelta(days=ACTIVE_WINDOW_DAYS)}).scalar_one())


def renew(now: datetime | None = None) -> LicenseState:
    now = now or _now()
    snap = snapshot(now)
    if snap.record is None or not snap.record.auth_token:
        raise LicenseError("not_activated", "a instalação ainda não foi ativada", 409)
    inst = installation(create=False)
    if inst is None:
        raise LicenseError("no_identity", "identidade da instalação não encontrada (LICENSE_STATE_DIR)", 500)
    try:
        req = build_request(inst, "renew", now, device_count=active_devices(now), version=settings.version)
        token = _post("/v1/renew", req)
        auth = _accept(token, inst, snap.record, now)
    except LicenseError as err:
        _fail(now, err)
        raise
    _store(token, auth, inst, now)
    return state(now)


def renew_if_due(now: datetime | None = None) -> str:
    """Chamado pelo worker a cada passada. Devolve o que fez (para log): não-ativado, nada, renovado, falhou:<código>."""
    now = now or _now()
    if not enabled():
        return "desligado"
    snap = snapshot(now)
    rec = snap.record
    if rec is None or not rec.auth_token:
        return "não ativado"
    interval = timedelta(hours=snap.auth.renew_after_hours if snap.auth else 24)
    if rec.last_error and rec.last_attempt_at and now - rec.last_attempt_at < timedelta(minutes=settings.license_retry_minutes):
        return "aguardando nova tentativa"          # vale também para recusa do fornecedor: não bater no serviço a cada passada
    if rec.last_success_at and now - rec.last_success_at < interval and not rec.last_error:
        return "em dia"
    try:
        renew(now)
        return "renovado"
    except LicenseError as err:
        return f"falhou:{err.code}"
