"""Regra de falta de validação (10 e 21 dias), edição dos prazos pelo fornecedor e alertas do painel. PostgreSQL real, dados SINTÉTICOS."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from promptshield_licensing import Installation, State, evaluate
from sqlalchemy import select
from test_service import T0, activate, refused, renew, verify

from lic_service import service
from lic_service.db import session_scope
from lic_service.models import ActivationCode, AuditEntry, Contract

pytestmark = pytest.mark.db

DAY = timedelta(days=1)


def weekly_contract(devices=50, months=12):
    with session_scope() as s:
        cust = service.create_customer(s, "Acme Ltda", "ti@acme.example", actor="henrique@vendor.example")
        k = service.create_weekly_contract(s, cust, devices, months, actor="henrique@vendor.example")
        return str(k.id), service.issue_code(s, k, T0, actor="henrique@vendor.example")


def overview_row(cid, now):
    with session_scope() as s:
        return next(r for r in service.overview(s, now) if str(r["id"]) == cid)


def test_weekly_contract_signs_the_policy_into_every_authorization(vendor_key):
    cid, code = weekly_contract()
    inst = Installation.create()
    a = verify(vendor_key, inst, activate(vendor_key, inst, code), T0)
    assert (a.renew_after_hours, a.warn_after_days, a.suspend_after_days) == (168, 10, 21)
    assert a.auth_expires == T0 + 28 * DAY                          # cobre a cadência (7) mais a suspensão (21)
    b = verify(vendor_key, inst, renew(vendor_key, inst, T0 + 7 * DAY), T0 + 7 * DAY)
    assert b.serial == 2 and b.issued_at == T0 + 7 * DAY and (b.warn_after_days, b.suspend_after_days) == (10, 21)


def test_end_to_end_timeline_server_signs_client_evaluates_and_a_new_validation_heals(vendor_key):
    cid, code = weekly_contract()
    inst = Installation.create()
    a = verify(vendor_key, inst, activate(vendor_key, inst, code), T0)
    due = T0 + 7 * DAY
    assert evaluate(a, due + 9 * DAY).state == State.ATIVO                                  # cliente ainda não é avisado
    warn = evaluate(a, due + 10 * DAY)
    assert warn.state == State.SEM_CONTATO and warn.inspecting
    stop = evaluate(a, due + 21 * DAY)
    assert stop.state == State.SUSPENSO and not stop.inspecting
    # o servidor volta: um pedido assinado em dia 40 traz autorização nova e a suspensão some sozinha
    healed = verify(vendor_key, inst, renew(vendor_key, inst, T0 + 40 * DAY), T0 + 40 * DAY)
    assert evaluate(healed, T0 + 40 * DAY).state == State.ATIVO and evaluate(healed, T0 + 40 * DAY).inspecting


def test_vendor_sees_the_alert_before_the_customer_does(vendor_key):
    cid, code = weekly_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code)
    assert overview_row(cid, T0 + 6 * DAY)["silence"] == "ok" and overview_row(cid, T0 + 6 * DAY)["alerts"] == []
    assert overview_row(cid, T0 + 7 * DAY + timedelta(hours=1))["silence"] == "ok"           # atraso pequeno não alarma
    internal = overview_row(cid, T0 + 8 * DAY)
    assert internal["silence"] == "internal" and internal["level"] == service.LEVEL_WARN and "Só você vê" in internal["alerts"][0][1]
    assert overview_row(cid, T0 + 17 * DAY)["silence"] == "client_warned"
    crit = overview_row(cid, T0 + 28 * DAY)
    assert crit["silence"] == "suspended" and crit["level"] == service.LEVEL_CRIT and "SUSPENSA" in crit["alerts"][0][1]
    renew(vendor_key, inst, T0 + 29 * DAY)
    assert overview_row(cid, T0 + 30 * DAY)["silence"] == "ok"                               # validou: o alerta some


def test_editing_the_remaining_days_changes_the_next_authorization_and_is_audited(vendor_key):
    cid, code = weekly_contract(months=12)
    inst = Installation.create()
    first = verify(vendor_key, inst, activate(vendor_key, inst, code), T0)
    with session_scope() as s:
        k = s.get(Contract, uuid.UUID(first.license_id))
        assert service.days_left(k, T0) == 365
        service.add_days(s, k, 30, "cortesia: migração atrasada", T0, actor="henrique@vendor.example")
        assert service.days_left(k, T0) == 395
        service.set_end_date(s, k, T0 + 100 * DAY, "contrato renegociado", T0, actor="henrique@vendor.example")
        assert service.days_left(k, T0) == 100
        assert refused(lambda: service.set_end_date(s, k, T0 + 10 * DAY, "  ", T0)).code == "reason_required"
        assert refused(lambda: service.set_end_date(s, k, T0 - DAY, "motivo ok", T0)).code == "bad_end"
        assert refused(lambda: service.add_days(s, k, 0, "motivo ok", T0)).code == "bad_days"
    second = verify(vendor_key, inst, renew(vendor_key, inst, T0 + DAY), T0 + DAY)
    assert second.contract_end == T0 + 100 * DAY                                             # a instalação vê o novo prazo na próxima validação
    with session_scope() as s:
        log = [(e.actor, e.action, e.detail.get("reason")) for e in s.execute(select(AuditEntry).where(AuditEntry.action == "contract.set_end").order_by(AuditEntry.id)).scalars()]
    assert log == [("henrique@vendor.example", "contract.set_end", "cortesia: migração atrasada"), ("henrique@vendor.example", "contract.set_end", "contrato renegociado")]


def test_pending_contract_edits_months_not_dates():
    with session_scope() as s:
        k = service.create_weekly_contract(s, service.create_customer(s, "Beta SA"), 10, 6)
        assert refused(lambda: service.set_end_date(s, k, T0 + 400 * DAY, "motivo ok", T0)).code == "not_activated"
        service.set_term_months(s, k, 24)
        assert k.term_months == 24 and service.days_left(k, T0) is None
        assert refused(lambda: service.set_term_months(s, k, 0)).code == "bad_months"


def test_terms_must_be_coherent_and_are_audited_with_before_and_after():
    with session_scope() as s:
        k = service.create_weekly_contract(s, service.create_customer(s, "Gama SA"), 10, 12)
        ok = dict(devices=20, tolerance_days=30, on_end="keep_inspection", renew_after_hours=168, auth_validity_days=28, warn_after_days=10,
                  suspend_after_days=21, note="negociado")
        service.update_terms(s, k, **ok, actor="henrique@vendor.example")
        assert (k.max_devices, k.tolerance_days, k.on_end, k.note) == (20, 30, "keep_inspection", "negociado")
        for bad, code in (({"warn_after_days": 21}, "bad_silence_rule"), ({"suspend_after_days": 500}, "bad_silence_rule"),
                          ({"auth_validity_days": 20}, "bad_validity"),            # não cobre 7 + 21
                          ({"renew_after_hours": 0}, "bad_cadence"), ({"on_end": "apagar"}, "bad_terms"), ({"devices": -1}, "bad_terms")):
            assert refused(lambda b=bad: service.update_terms(s, k, **{**ok, **b})).code == code
        service.update_terms(s, k, **{**ok, "warn_after_days": None, "suspend_after_days": None, "auth_validity_days": 7, "renew_after_hours": 24})   # desligar a regra
        assert k.warn_after_days is None and k.suspend_after_days is None
        entry = s.execute(select(AuditEntry).where(AuditEntry.action == "contract.terms").order_by(AuditEntry.id)).scalars().first()
        assert entry.detail["before"]["max_devices"] == 10 and entry.detail["after"]["max_devices"] == 20 and entry.actor == "henrique@vendor.example"


def test_a_new_activation_code_cancels_the_previous_unused_ones():
    with session_scope() as s:
        k = service.create_weekly_contract(s, service.create_customer(s, "Delta SA"), 10, 12)
        first = service.issue_code(s, k, T0)
        second = service.issue_code(s, k, T0 + timedelta(hours=1))
        s.flush()
        valid = [c for c in s.execute(select(ActivationCode).where(ActivationCode.contract_id == k.id)).scalars() if c.expires_at > T0 + timedelta(hours=1)]
        assert len(valid) == 1 and valid[0].code_hash == service.hash_code(second) and service.hash_code(first) != valid[0].code_hash


def test_overview_flags_contract_end_device_limit_and_closed_and_pending(vendor_key):
    cid, code = weekly_contract(devices=10, months=1)
    inst = Installation.create()
    activate(vendor_key, inst, code)
    renew(vendor_key, inst, T0 + 2 * DAY, device_count=14)
    row = overview_row(cid, T0 + 3 * DAY)
    texts = " | ".join(t for _, t in row["alerts"])
    assert "Vence em" in texts and "14 máquinas em uso para um limite de 10" in texts and row["devices_used"] == 14
    with session_scope() as s:
        service.close_contract(s, s.get(Contract, uuid.UUID(cid)), "cancelado a pedido", T0)
    assert any("ENCERRADO" in t for _, t in overview_row(cid, T0 + 3 * DAY)["alerts"])
    with session_scope() as s:
        k = service.create_weekly_contract(s, service.create_customer(s, "Pendente SA"), 5, 12)
        pending_id = str(k.id)
    assert any("sem código válido" in t for _, t in overview_row(pending_id, T0)["alerts"])


def test_refused_requests_show_up_as_internal_alerts(vendor_key):
    cid, code = weekly_contract()
    stranger = Installation.create()
    from fastapi.testclient import TestClient
    from promptshield_licensing import build_request

    from lic_service.main import app
    c = TestClient(app)
    r = c.post("/v1/renew", json={"request": build_request(stranger, "renew", service.utcnow())})
    assert r.status_code == 403 and r.json()["code"] == "unknown_installation"
    with session_scope() as s:
        refusals = service.recent_refusals(s, service.utcnow())
    assert refusals and refusals[0]["action"] == "renew.refused" and refusals[0]["code"] == "unknown_installation"
