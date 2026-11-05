"""Licença on-premise: estado, ativação por código e renovação imediata. Com LICENSE_MODE=off só /status responde (mode=off)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import audit, license_client, ratelimit
from app.config import settings
from app.db import tenant_session
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1/license", tags=["licença"])


class ActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[str, Field(min_length=10, max_length=200)]


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _view() -> dict:
    snap = license_client.snapshot()
    st, a, rec = snap.state, snap.auth, snap.record
    inst = license_client.installation(create=False)
    return {
        "mode": "onprem", "state": st.state.value, "message": st.message, "can_enroll": st.can_enroll, "inspecting": st.inspecting,
        "deadline": _iso(st.deadline), "days_left": st.days_left, "max_devices": st.max_devices,
        "installation_id": inst.installation_id if inst else None, "server_configured": bool(settings.license_server_url and settings.license_public_key),
        "customer": a.customer if a else None, "serial": a.serial if a else None, "on_end": a.on_end if a else None,
        "contract_start": _iso(a.contract_start) if a else None, "contract_end": _iso(a.contract_end) if a else None,
        "tolerance_end": _iso(a.tolerance_end) if a else None, "auth_expires": _iso(a.auth_expires) if a else None,
        "last_success_at": _iso(rec.last_success_at) if rec else None, "last_attempt_at": _iso(rec.last_attempt_at) if rec else None,
        "last_attempt_failed": bool(rec.last_attempt_failed) if rec else False, "last_error": rec.last_error if rec else None,
        "problem": snap.problem,
    }


@router.get("/status", summary="Estado da licença desta instalação (o que o console e os sensores devem mostrar)")
def status(_: Annotated[Principal, Depends(require_roles(*READ_ROLES))]) -> dict:
    if not license_client.enabled():
        return {"mode": "off", "state": "ativo", "message": "Licenciamento por autorização desligado (LICENSE_MODE=off).", "can_enroll": True, "inspecting": True}
    return _view()


def _raise(err: license_client.LicenseError) -> None:
    code = err.http if err.http in (400, 403, 409, 429, 503) else 502
    raise HTTPException(code, detail={"code": err.code, "message": err.detail})


def _require_mode() -> None:
    if not license_client.enabled():
        raise HTTPException(404, "licenciamento por autorização desligado (LICENSE_MODE=off)")


@router.post("/activate", summary="Informa o código de ativação do fornecedor (uso único). Vincula este servidor ao contrato")
def activate(body: ActivateIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    _require_mode()
    wait = ratelimit.check(f"license-activate:{p.id}", 10)
    if wait is not None:
        raise HTTPException(429, "muitas tentativas", headers={"Retry-After": str(wait)})
    try:
        license_client.activate(body.code)
    except license_client.LicenseError as err:
        with tenant_session(p.tenant_id) as s:
            audit.write(s, p, "license.activate_failed", "license", None, {"code": err.code})
        _raise(err)
    with tenant_session(p.tenant_id) as s:
        audit.write(s, p, "license.activate", "license", None, {})
    return _view()


@router.post("/renew", summary="Renova agora a autorização (o worker já renova sozinho, por exemplo uma vez por dia)")
def renew(p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    _require_mode()
    wait = ratelimit.check(f"license-renew:{p.id}", 6)
    if wait is not None:
        raise HTTPException(429, "muitas tentativas", headers={"Retry-After": str(wait)})
    try:
        license_client.renew()
    except license_client.LicenseError as err:
        _raise(err)
    with tenant_session(p.tenant_id) as s:
        audit.write(s, p, "license.renew", "license", None, {})
    return _view()
