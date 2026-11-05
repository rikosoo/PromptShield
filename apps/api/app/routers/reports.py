"""Relatórios: gerar na hora (PDF/CSV), listar, baixar e agendar."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app import audit, reports
from app.db import tenant_session
from app.models import Report, ReportSchedule, Tenant
from app.schemas import ReportRequest, ScheduleIn
from app.security import Principal, require_roles

router = APIRouter(prefix="/v1/reports", tags=["relatórios"])
ROLES = ("admin", "analista", "auditor")
MEDIA = {"pdf": "application/pdf", "csv": "text/csv; charset=utf-8"}
MAX_DAYS = 366


def _view(r: Report) -> dict:
    return {"id": str(r.id), "kind": r.kind, "format": r.format, "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(), "sha256": r.sha256, "created_by": r.created_by,
            "created_at": r.created_at.isoformat(), "size": len(r.content), "scheduled": r.schedule_id is not None}


@router.post("", status_code=201, summary="Gera um relatório e guarda uma cópia")
def generate(body: ReportRequest, p: Annotated[Principal, Depends(require_roles(*ROLES))]) -> dict:
    if body.end < body.start or (body.end - body.start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"período inválido (máximo {MAX_DAYS} dias)")
    with tenant_session(p.tenant_id) as s:
        data = reports.collect(s, s.get(Tenant, p.tenant_id), body.kind, body.start, body.end)
        content, digest = reports.render(data, body.format)
        r = Report(tenant_id=p.tenant_id, kind=body.kind, format=body.format, period_start=body.start, period_end=body.end,
                   content=content, sha256=digest, created_by=p.email or p.id)
        s.add(r)
        s.flush()
        audit.write(s, p, "report.generate", "report", str(r.id), {"kind": body.kind, "format": body.format})
        return _view(r)


@router.get("", summary="Relatórios gerados (mais recentes primeiro)")
def list_reports(p: Annotated[Principal, Depends(require_roles(*ROLES))]) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        return [_view(r) for r in s.execute(select(Report).order_by(Report.created_at.desc()).limit(100)).scalars()]


@router.get("/schedules")
def list_schedules(p: Annotated[Principal, Depends(require_roles(*ROLES))]) -> list[dict]:
    with tenant_session(p.tenant_id) as s:
        return [{"id": str(x.id), "kind": x.kind, "format": x.format, "frequency": x.frequency, "recipients": x.recipients,
                 "enabled": x.enabled, "last_period_end": x.last_period_end.isoformat() if x.last_period_end else None}
                for x in s.execute(select(ReportSchedule).order_by(ReportSchedule.created_at)).scalars()]


@router.post("/schedules", status_code=201, summary="Agenda relatório mensal ou semanal (gerado pelo worker)")
def create_schedule(body: ScheduleIn, p: Annotated[Principal, Depends(require_roles("admin"))]) -> dict:
    import re

    for r in body.recipients:
        if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", r):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"e-mail inválido: {r}")
    with tenant_session(p.tenant_id) as s:
        x = ReportSchedule(tenant_id=p.tenant_id, **body.model_dump())
        s.add(x)
        s.flush()
        audit.write(s, p, "report.schedule", "schedule", str(x.id), body.model_dump())
        return {"id": str(x.id), **body.model_dump(), "enabled": True}


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> None:
    with tenant_session(p.tenant_id) as s:
        x = s.get(ReportSchedule, schedule_id)
        if x is None:
            raise HTTPException(404, "agendamento não encontrado")
        s.delete(x)
        audit.write(s, p, "report.schedule_delete", "schedule", str(schedule_id))


@router.delete("/{report_id}", status_code=204, summary="Apaga um relatório gerado")
def delete_report(report_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles("admin"))]) -> None:
    with tenant_session(p.tenant_id) as s:
        r = s.get(Report, report_id)
        if r is None:
            raise HTTPException(404, "relatório não encontrado")
        s.delete(r)
        audit.write(s, p, "report.delete", "report", str(report_id), {"kind": r.kind})


@router.get("/{report_id}/download")
def download(report_id: uuid.UUID, p: Annotated[Principal, Depends(require_roles(*ROLES))]) -> Response:
    with tenant_session(p.tenant_id) as s:
        r = s.get(Report, report_id)
        if r is None:
            raise HTTPException(404, "relatório não encontrado")
        audit.write(s, p, "report.download", "report", str(report_id))
        name = f"promptshield-{r.kind}-{r.period_start}-{r.period_end}.{r.format}"
        return Response(r.content, media_type=MEDIA[r.format], headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                                           "Cache-Control": "no-store"})
