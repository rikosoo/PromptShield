"""Console: cadastro das palavras-chave. Leitura para quem lê o painel; escrita só do administrador; tudo auditado."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.db import tenant_session
from app.models import KeywordRule
from app.security import READ_ROLES, Principal, require_roles

router = APIRouter(prefix="/v1/keywords", tags=["palavras-chave"])
MAX_KEYWORDS = 200
Admin = Annotated[Principal, Depends(require_roles("admin"))]
Reader = Annotated[Principal, Depends(require_roles(*READ_ROLES))]


class KeywordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=2, max_length=100)
    whole_word: bool = False
    score: int | None = Field(default=None, ge=0, le=100, description="vazio: vale a pontuação calculada pelo motor")
    enabled: bool = True
    note: str | None = Field(default=None, max_length=300)

    @field_validator("term", "note")
    @classmethod
    def _line(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if any(ord(c) < 32 for c in v):
            raise ValueError("uma linha só, sem caracteres de controle")
        return v or None

    @field_validator("term")
    @classmethod
    def _need(cls, v: str | None) -> str:
        if not v or len(v) < 2:
            raise ValueError("palavra obrigatória (mínimo 2 caracteres)")
        return v


def _view(k: KeywordRule) -> dict:
    return {"id": str(k.id), "term": k.term, "whole_word": k.whole_word, "score": k.score, "enabled": k.enabled, "note": k.note,
            "created_by": k.created_by, "created_at": k.created_at.isoformat()}


def _snap(k: KeywordRule) -> dict:
    return {"term": k.term, "whole_word": k.whole_word, "score": k.score, "enabled": k.enabled}


@router.get("", summary="Palavras-chave monitoradas")
def list_keywords(p: Reader) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        return [_view(k) for k in s.execute(select(KeywordRule).order_by(KeywordRule.term)).scalars()]


@router.post("", status_code=201, summary="Cadastra uma palavra: todo prompt que a contiver gera alerta")
def add_keyword(body: KeywordIn, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        if s.execute(select(func.count()).select_from(KeywordRule)).scalar_one() >= MAX_KEYWORDS:
            raise HTTPException(status.HTTP_409_CONFLICT, f"limite de {MAX_KEYWORDS} palavras")
        k = KeywordRule(tenant_id=p.tenant_id, created_by=p.id, **body.model_dump())
        s.add(k)
        try:
            s.flush()
        except IntegrityError:
            raise HTTPException(status.HTTP_409_CONFLICT, "essa palavra já está cadastrada") from None
        audit.write(s, p, "keyword.add", "keyword", str(k.id), {"after": _snap(k)})
        s.refresh(k)
        return _view(k)


@router.put("/{keyword_id}", summary="Altera a palavra, a pontuação ou liga/desliga")
def update_keyword(keyword_id: uuid.UUID, body: KeywordIn, p: Admin) -> dict:
    with tenant_session(p.tenant_id) as s:
        k = s.get(KeywordRule, keyword_id)
        if k is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "palavra não encontrada")
        before = _snap(k)
        for f, v in body.model_dump().items():
            setattr(k, f, v)
        try:
            s.flush()
        except IntegrityError:
            raise HTTPException(status.HTTP_409_CONFLICT, "essa palavra já está cadastrada") from None
        audit.write(s, p, "keyword.update", "keyword", str(k.id), {"before": before, "after": _snap(k)})
        s.refresh(k)
        return _view(k)


@router.delete("/{keyword_id}", status_code=204, summary="Remove a palavra (alertas já gerados continuam)")
def remove_keyword(keyword_id: uuid.UUID, p: Admin) -> Response:
    with tenant_session(p.tenant_id) as s:
        k = s.get(KeywordRule, keyword_id)
        if k is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "palavra não encontrada")
        audit.write(s, p, "keyword.remove", "keyword", str(k.id), {"before": _snap(k)})
        s.delete(k)
    return Response(status_code=204)
