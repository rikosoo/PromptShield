"""Worker: entrega a fila de notificações e gera relatórios agendados.

    python -m app.worker            # laço contínuo (intervalo em WORKER_INTERVAL, padrão 10 s)
    python -m app.worker --once     # uma passada (útil em cron e nos testes)

Usa o papel restrito da aplicação (DATABASE_URL), com RLS; só `list_tenant_ids()` cruza tenants.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text

from app import audit_system, notifier, reports, retention
from app.db import anonymous_session, tenant_session
from app.models import Report, ReportSchedule, Tenant

log = logging.getLogger("promptshield.worker")


def due_period(freq: str, today: date) -> tuple[date, date]:
    """Último período COMPLETO anterior a `today`: mês civil anterior ou semana ISO anterior (segunda a domingo)."""
    if freq == "mensal":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        return end.replace(day=1), end
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def run_schedules(tenant_id, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    made = 0
    with tenant_session(tenant_id) as s:
        tenant = s.get(Tenant, tenant_id)
        if tenant.suspended_at:      # contrato suspenso: não gera nem envia relatórios (a retenção continua rodando)
            return 0
        for sch in s.execute(select(ReportSchedule).where(ReportSchedule.enabled.is_(True))).scalars().all():
            start, end = due_period(sch.frequency, today)
            if sch.last_period_end is not None and sch.last_period_end >= end:
                continue  # este período já foi gerado: não repete
            data = reports.collect(s, tenant, sch.kind, start, end)
            content, digest = reports.render(data, sch.format)
            r = Report(tenant_id=tenant_id, kind=sch.kind, format=sch.format, period_start=start, period_end=end, content=content,
                       sha256=digest, created_by="agendamento", schedule_id=sch.id)
            s.add(r)
            sch.last_period_end = end
            made += 1
            errors = []
            for to in sch.recipients:
                try:
                    notifier.send_email_with_attachment(
                        to, f"[PromptShield] {data['title']} ({start:%d/%m/%Y} a {end:%d/%m/%Y})",
                        "Relatório gerado automaticamente. Em anexo.", f"promptshield-{sch.kind}-{start}-{end}.{sch.format}",
                        content, "application/pdf" if sch.format == "pdf" else "text/csv")
                except notifier.DeliveryError as exc:
                    errors.append(f"{to}: {exc}")
            audit_system.write(s, tenant_id, "report.scheduled", "schedule", str(sch.id),
                               {"period": f"{start}..{end}", "email_errors": errors})
    return made


def run_retention(tenant_id) -> bool:
    with tenant_session(tenant_id) as s:
        if not retention.due(s, tenant_id):
            return False
        retention.run(s, tenant_id)
        return True


def run_once() -> dict:
    out = notifier.deliver_all()
    try:
        from app import license_client

        out["license"] = 0 if license_client.renew_if_due() in ("desligado", "não ativado", "em dia", "aguardando nova tentativa") else 1
    except Exception:  # noqa: BLE001 - o worker não pode morrer por causa do licenciamento
        log.exception("falha ao renovar a licença")
    with anonymous_session() as s:
        ids = [r.tenant_id for r in s.execute(text("SELECT tenant_id FROM list_tenant_ids()"))]
    out["reports"] = sum(run_schedules(t) for t in ids)
    out["retention"] = sum(run_retention(t) for t in ids)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.worker")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    interval = float(os.environ.get("WORKER_INTERVAL", "10"))
    while True:
        try:
            res = run_once()
            if any(res.values()):
                log.info("passada: %s", res)  # só contagens; nunca conteúdo
        except Exception:  # o worker não pode morrer por um tenant com problema
            log.exception("falha na passada do worker")
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
