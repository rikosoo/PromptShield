"""Atualizações assistidas e pacotes de regras: só o administrador. Cada ação é auditada. Com LICENSE_MODE=off (SaaS e desenvolvimento) não há nada a atualizar."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app import audit, license_client, rulepacks, updates
from app.db import tenant_session
from app.security import Principal, require_roles

router = APIRouter(prefix="/v1", tags=["atualizações"])
Admin = Annotated[Principal, Depends(require_roles("admin"))]


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=3, max_length=40)


class RetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["app", "rules"]


class PhaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Literal["shadow", "active", "retired"]


def _on() -> None:
    if not license_client.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "atualizações assistidas só existem com o licenciamento on-premise ligado (LICENSE_MODE=onprem)")


@router.get("/updates", summary="Versão nova da aplicação e dos pacotes de regras (aviso do fornecedor, andamento e pacotes guardados)")
def get_updates(p: Admin) -> dict:
    if not license_client.enabled():
        return {"mode": "off"}
    return {"mode": "onprem", **updates.summary(), "packs": rulepacks.listing()}


@router.post("/updates/app/approve", summary="Autoriza BAIXAR a versão nova (não instala nada: o administrador roda atualizar.sh no servidor)")
def approve_app(body: ApproveIn, p: Admin) -> dict:
    _on()
    try:
        updates.approve_app(body.version, p.email or p.id)
    except updates.UpdateError as exc:
        raise HTTPException(exc.http, exc.detail) from exc
    with tenant_session(p.tenant_id) as s:
        audit.write(s, p, "update.approve", "update", body.version, {"kind": "app", "version": body.version})
    return {"ok": True, "status": "approved"}


@router.post("/updates/retry", summary="Tenta de novo um download ou pacote que falhou")
def retry(body: RetryIn, p: Admin) -> dict:
    _on()
    try:
        updates.retry(body.kind)
    except updates.UpdateError as exc:
        raise HTTPException(exc.http, exc.detail) from exc
    with tenant_session(p.tenant_id) as s:
        audit.write(s, p, "update.retry", "update", body.kind, {"kind": body.kind})
    return {"ok": True}


@router.get("/rule-packs/{pack_id}", summary="Um pacote de regras: o que ele faz, regra por regra, e quantas vezes cada regra casou")
def pack_detail(pack_id: uuid.UUID, p: Admin) -> dict:
    _on()
    d = rulepacks.detail(pack_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pacote não encontrado")
    return d


@router.post("/rule-packs/{pack_id}/phase", summary="Muda a fase do pacote: shadow (sem efeito, só registra), active (vale) ou retired (volta ao padrão de fábrica)")
def pack_phase(pack_id: uuid.UUID, body: PhaseIn, p: Admin) -> dict:
    _on()
    try:
        row = rulepacks.transition(pack_id, body.to, p.email or p.id)
    except rulepacks.PackStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT if "não dá" in str(exc) else status.HTTP_404_NOT_FOUND, str(exc)) from exc
    with tenant_session(p.tenant_id) as s:
        audit.write(s, p, f"rulepack.{body.to}", "rule_pack", str(row.id), {"version": row.version})
    return {"ok": True, "version": row.version, "status": row.status}
