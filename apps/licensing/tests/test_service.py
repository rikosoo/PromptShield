"""Serviço de licenças contra PostgreSQL real: ativação, renovação, prazos, encerramento, vínculo e segurança dos pedidos. Dados SINTÉTICOS."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from promptshield_licensing import Installation, State, build_request, evaluate, verify_authorization
from sqlalchemy import select, text

from lic_service import service
from lic_service.db import session_scope
from lic_service.models import AuditEntry, Contract, IssuedAuthorization
from lic_service.models import Installation as InstRow

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def setup_contract(devices=100, months=12, **kw):
    with session_scope() as s:
        cust = service.create_customer(s, "Acme Ltda", "ti@acme.example")
        k = service.create_contract(s, cust, devices, months, **kw)
        code = service.issue_code(s, k, T0)
        return str(k.id), code


def call(fn, key, token, now):
    with session_scope() as s:
        return fn(s, key, token, now)


def activate(vendor_key, inst, code, now=T0, **fields):
    return call(service.activate, vendor_key, build_request(inst, "activate", now, code=code, **fields), now)


def renew(vendor_key, inst, now, **fields):
    return call(service.renew, vendor_key, build_request(inst, "renew", now, **fields), now)


def verify(vendor_key, inst, token, now):
    return verify_authorization(token, vendor_key.public_key(), inst.installation_id, now)


def refused(fn):
    with pytest.raises(service.ServiceError) as e:
        fn()
    return e.value


# ---------- ativação ----------
def test_activation_binds_contract_starts_the_term_and_returns_a_signed_authorization(vendor_key):
    cid, code = setup_contract(devices=100, months=12)
    assert code.startswith("psa_")
    inst = Installation.create()
    token = activate(vendor_key, inst, code, hostname="srv-acme", version="0.3.0")
    a = verify(vendor_key, inst, token, T0)
    assert a.license_id == cid and a.max_devices == 100 and a.customer == "Acme Ltda" and a.status == "active" and a.serial == 1
    assert a.contract_start == T0 and a.contract_end == datetime(2027, 11, 3, 12, 0, tzinfo=timezone.utc)
    assert a.auth_expires == T0 + timedelta(days=7)                                # autorização curta, contrato longo
    assert evaluate(a, T0).state == State.ATIVO
    with session_scope() as s:
        k = s.get(Contract, cid)
        assert k.status == "ativo" and k.starts_at == T0
        row = s.execute(select(InstRow)).scalar_one()
        assert row.installation_id == inst.installation_id and row.public_key == inst.public_b64 and row.hostname == "srv-acme"
        assert s.execute(text("SELECT code_hash FROM lic_activation_codes")).scalar() != code            # só o hash fica no banco
        assert code not in str(s.execute(text("SELECT * FROM lic_audit")).all())


def test_code_is_single_use_short_lived_and_unknown_codes_are_refused(vendor_key):
    _, code = setup_contract()
    assert refused(lambda: activate(vendor_key, Installation.create(), "psa_00000000_inventado")).code == "invalid_code"
    assert refused(lambda: activate(vendor_key, Installation.create(), code, now=T0 + timedelta(days=8))).code == "code_expired"
    activate(vendor_key, Installation.create(), code)
    assert refused(lambda: activate(vendor_key, Installation.create(), code)).code == "code_used"


def test_two_installations_racing_for_the_same_code_only_one_wins(vendor_key):
    _, code = setup_contract()
    results = []

    def go():
        try:
            activate(vendor_key, Installation.create(), code)
            results.append("ok")
        except service.ServiceError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["code_used"] * 5 + ["ok"]
    with session_scope() as s:
        assert s.execute(select(InstRow)).scalars().all().__len__() == 1


def test_activation_needs_proof_of_the_private_key_and_a_fresh_request(vendor_key):
    _, code = setup_contract()
    inst = Installation.create()
    req = build_request(inst, "activate", T0, code=code)
    assert refused(lambda: call(service.activate, vendor_key, req, T0 + timedelta(minutes=6))).code == "invalid_request"      # fora da janela
    assert refused(lambda: call(service.activate, vendor_key, req.replace(".", "x", 1), T0)).code == "invalid_request"
    assert refused(lambda: call(service.activate, vendor_key, build_request(inst, "renew", T0, code=code), T0)).code == "invalid_request"
    call(service.activate, vendor_key, req, T0)
    assert refused(lambda: call(service.activate, vendor_key, req, T0)).code in ("replay", "code_used")


def test_a_contract_has_one_active_installation_until_the_vendor_unbinds(vendor_key):
    cid, code = setup_contract()
    first = Installation.create()
    activate(vendor_key, first, code)
    with session_scope() as s:
        k = s.get(Contract, cid)
        assert refused(lambda: service.issue_code(s, k, T0)).code == "already_bound"
        service.unbind(s, k, T0)
        new_code = service.issue_code(s, k, T0)
    assert refused(lambda: renew(vendor_key, first, T0 + timedelta(hours=1))).code == "unknown_installation"     # a antiga perdeu o vínculo
    second = Installation.create()
    token = activate(vendor_key, second, new_code, now=T0 + timedelta(hours=2))
    a = verify(vendor_key, second, token, T0 + timedelta(hours=2))
    assert a.serial == 2 and a.contract_start == T0                       # o prazo NÃO recomeça numa troca de servidor
    with session_scope() as s:
        assert s.execute(select(InstRow).where(InstRow.unbound_at.is_(None))).scalar_one().installation_id == second.installation_id


def test_an_installation_cannot_serve_two_contracts(vendor_key):
    _, code1 = setup_contract()
    _, code2 = setup_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code1)
    assert refused(lambda: activate(vendor_key, inst, code2)).code == "installation_in_use"


# ---------- renovação e os dois prazos ----------
def test_renewal_issues_a_new_authorization_every_time_with_increasing_serial(vendor_key):
    _, code = setup_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code)
    t1 = T0 + timedelta(days=1)
    a = verify(vendor_key, inst, renew(vendor_key, inst, t1, device_count=42, version="0.3.1"), t1)
    assert a.serial == 2 and a.auth_expires == t1 + timedelta(days=7) and a.status == "active"
    a3 = verify(vendor_key, inst, renew(vendor_key, inst, t1 + timedelta(days=1)), t1 + timedelta(days=1))
    assert a3.serial == 3
    with session_scope() as s:
        row = s.execute(select(InstRow)).scalar_one()
        assert row.last_device_count == 42 and row.product_version == "0.3.1" and row.last_seen_at == t1 + timedelta(days=1)
        assert [x.serial for x in s.execute(select(IssuedAuthorization).order_by(IssuedAuthorization.serial)).scalars()] == [1, 2, 3]


def test_renewal_rejects_replays_forged_keys_and_strangers(vendor_key):
    _, code = setup_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code)
    req = build_request(inst, "renew", T0 + timedelta(hours=1))
    call(service.renew, vendor_key, req, T0 + timedelta(hours=1))
    assert refused(lambda: call(service.renew, vendor_key, req, T0 + timedelta(hours=1))).code == "replay"
    # alguém que conhece o identificador da instalação, mas não a chave privada
    attacker = Installation.create()
    forged = build_request(attacker, "renew", T0 + timedelta(hours=1)).replace(attacker.installation_id, inst.installation_id)
    assert refused(lambda: call(service.renew, vendor_key, forged, T0 + timedelta(hours=1))).code in ("invalid_request", "unknown_installation")
    assert refused(lambda: renew(vendor_key, Installation.create(), T0)).code == "unknown_installation"
    assert refused(lambda: call(service.renew, vendor_key, "lixo", T0)).code == "unknown_installation"


def test_authorization_is_capped_by_the_contract_end_plus_the_agreed_tolerance(vendor_key):
    cid, code = setup_contract(months=1, tolerance_days=10)
    inst = Installation.create()
    activate(vendor_key, inst, code)
    end = datetime(2026, 12, 3, 12, 0, tzinfo=timezone.utc)
    near = end - timedelta(days=2)
    assert verify(vendor_key, inst, renew(vendor_key, inst, near), near).auth_expires == near + timedelta(days=7)      # 5 dias após o fim: dentro da tolerância
    late = end + timedelta(days=8)
    a = verify(vendor_key, inst, renew(vendor_key, inst, late), late)
    assert a.auth_expires == end + timedelta(days=10) and evaluate(a, late).state == State.EM_TOLERANCIA
    assert refused(lambda: renew(vendor_key, inst, end + timedelta(days=11))).code == "contract_expired"             # passou da tolerância
    assert refused(lambda: renew(vendor_key, inst, end + timedelta(days=11))).http == 403


def test_extending_the_contract_changes_the_next_authorization_and_devices_follow(vendor_key):
    cid, code = setup_contract(months=1, tolerance_days=0)
    inst = Installation.create()
    activate(vendor_key, inst, code)
    t = T0 + timedelta(days=29)
    short = verify(vendor_key, inst, renew(vendor_key, inst, t), t)
    assert short.auth_expires == short.contract_end                          # sem tolerância, corta no fim do contrato
    with session_scope() as s:
        k = s.get(Contract, cid)
        service.extend_contract(s, k, 12)
        service.set_devices(s, k, 250)
    t2 = T0 + timedelta(days=30)
    longer = verify(vendor_key, inst, renew(vendor_key, inst, t2), t2)
    assert longer.auth_expires == t2 + timedelta(days=7) and longer.max_devices == 250 and longer.contract_end > short.contract_end


def test_closing_is_communicated_at_renewal_and_reopening_restores(vendor_key):
    cid, code = setup_contract(on_end="keep_inspection")
    inst = Installation.create()
    activate(vendor_key, inst, code)
    with session_scope() as s:
        service.close_contract(s, s.get(Contract, cid), "contrato cancelado a pedido", T0 + timedelta(days=5))
    t = T0 + timedelta(days=6)
    a = verify(vendor_key, inst, renew(vendor_key, inst, t), t)
    ev = evaluate(a, t)
    assert a.status == "closed" and ev.state == State.ENCERRADO and ev.inspecting and not ev.can_enroll       # política contratada: continua inspecionando
    with session_scope() as s:
        k = s.get(Contract, cid)
        assert refused(lambda: service.issue_code(s, k, t)).code == "contract_closed"
        service.reopen_contract(s, k, t)
    t2 = t + timedelta(days=1)
    assert evaluate(verify(vendor_key, inst, renew(vendor_key, inst, t2), t2), t2).state == State.ATIVO


def test_audit_trail_records_everything_and_cannot_be_changed(vendor_key):
    cid, code = setup_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code)
    renew(vendor_key, inst, T0 + timedelta(hours=1))
    with session_scope() as s:
        actions = [e.action for e in s.execute(select(AuditEntry).order_by(AuditEntry.id)).scalars()]
    assert actions == ["customer.create", "contract.create", "code.issue", "installation.activate", "installation.renew"]
    with session_scope() as s:
        with pytest.raises(Exception, match="imut"):
            s.execute(text("DELETE FROM lic_audit"))
