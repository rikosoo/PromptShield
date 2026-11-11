"""Núcleo do licenciamento: assinatura, vínculo com a instalação, regra dos dois prazos, pedidos e estados. Tudo com relógio injetado."""
from datetime import datetime, timedelta, timezone

import pytest

from promptshield_licensing import (
    AuthorizationError,
    Installation,
    RequestError,
    State,
    b64d,
    b64e,
    build_request,
    evaluate,
    fingerprint,
    generate_signing_key,
    issue_authorization,
    load_private_key,
    load_public_key,
    public_key_b64,
    verify_authorization,
    verify_request,
)
from promptshield_licensing.crypto import private_pem

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
END = T0 + timedelta(days=365)


@pytest.fixture
def vendor():
    return generate_signing_key()


@pytest.fixture
def inst():
    return Installation.create()


def issue(vendor, inst, now=T0, **over):
    kw = dict(license_id="lic-1", installation_id=inst.installation_id, customer="Acme", max_devices=100, contract_start=T0, contract_end=END,
              tolerance_days=15, status="active", on_end="stop_inspection", serial=1, now=now, validity=timedelta(days=7))
    kw.update(over)
    return issue_authorization(vendor, **kw)


# ---------- chaves e assinatura ----------
def test_key_formats_round_trip(vendor):
    assert load_private_key(private_pem(vendor)).public_key().public_bytes_raw() == vendor.public_key().public_bytes_raw()
    import base64
    assert load_private_key(base64.b64encode(private_pem(vendor))).public_key().public_bytes_raw() == vendor.public_key().public_bytes_raw()
    pub = public_key_b64(vendor)
    assert load_public_key(pub).public_bytes_raw() == vendor.public_key().public_bytes_raw()
    assert len(fingerprint(pub)) == 32 and fingerprint(pub) == fingerprint(vendor.public_key())
    assert b64d(b64e(b"\x00\xff\x10")) == b"\x00\xff\x10"


def test_authorization_verifies_and_is_bound_to_the_installation(vendor, inst):
    token, auth = issue(vendor, inst)
    pub = vendor.public_key()
    got = verify_authorization(token, pub, inst.installation_id, T0)
    assert got == auth and got.max_devices == 100 and got.serial == 1
    other = Installation.create()
    with pytest.raises(AuthorizationError, match="outra instalação"):
        verify_authorization(token, pub, other.installation_id, T0)
    with pytest.raises(AuthorizationError):
        verify_authorization(token, generate_signing_key().public_key(), inst.installation_id, T0)   # chave do fornecedor errada


def test_tampering_is_detected(vendor, inst):
    token, _ = issue(vendor, inst)
    prefix, payload, sig = token.split(".")
    forged = b64e(b64d(payload).replace(b'"max_devices":100', b'"max_devices":999'))
    with pytest.raises(AuthorizationError):
        verify_authorization(f"{prefix}.{forged}.{sig}", vendor.public_key(), inst.installation_id, T0)
    for bad in ("", "x", "pl1.a", "pl1.a.b.c", token + "x", token.replace("pl1", "pr1", 1)):
        with pytest.raises(AuthorizationError):
            verify_authorization(bad, vendor.public_key(), inst.installation_id, T0)


def test_a_request_is_never_accepted_as_an_authorization(vendor, inst):
    req = build_request(inst, "renew", T0)
    with pytest.raises(AuthorizationError):
        verify_authorization(req, inst.private.public_key(), inst.installation_id, T0)


# ---------- os dois prazos ----------
def test_authorization_never_outlives_contract_plus_tolerance(vendor, inst):
    near_end = END - timedelta(days=2)
    _, a = issue(vendor, inst, now=near_end)
    assert a.auth_expires == near_end + timedelta(days=7)            # ainda dentro do contrato: 7 dias inteiros
    _, a = issue(vendor, inst, now=END - timedelta(days=1), tolerance_days=0)
    assert a.auth_expires == END                                      # sem tolerância: corta no fim do contrato
    _, a = issue(vendor, inst, now=END - timedelta(days=1), tolerance_days=3)
    assert a.auth_expires == END + timedelta(days=3)                  # com tolerância explícita: corta no fim dela
    with pytest.raises(AuthorizationError, match="tolerância"):
        issue(vendor, inst, now=END + timedelta(days=16))              # passou da tolerância: não se emite ativa
    with pytest.raises(AuthorizationError):
        issue(vendor, inst, contract_end=T0)


def test_a_forged_long_authorization_is_refused_even_if_signed(vendor, inst):
    # um fornecedor com bug ou chave vazada que assine além do contrato: o produto recusa
    import json

    from promptshield_licensing.authorization import PREFIX
    from promptshield_licensing.crypto import sign_blob
    token, auth = issue(vendor, inst)
    claims = auth.to_claims()
    claims["auth_expires"] = (END + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    bad = sign_blob(vendor, PREFIX, json.dumps(claims, sort_keys=True).encode())
    with pytest.raises(AuthorizationError, match="passa do fim do contrato"):
        verify_authorization(bad, vendor.public_key(), inst.installation_id, T0)


def test_serial_rollback_and_future_dated_authorization(vendor, inst):
    token, _ = issue(vendor, inst, serial=5)
    with pytest.raises(AuthorizationError, match="mais antiga"):
        verify_authorization(token, vendor.public_key(), inst.installation_id, T0, min_serial=6)
    assert verify_authorization(token, vendor.public_key(), inst.installation_id, T0, min_serial=5).serial == 5
    future, _ = issue(vendor, inst, now=T0 + timedelta(hours=2))
    with pytest.raises(AuthorizationError, match="ainda não vale"):
        verify_authorization(future, vendor.public_key(), inst.installation_id, T0)
    assert verify_authorization(future, vendor.public_key(), inst.installation_id, T0 + timedelta(hours=2, minutes=-5))


# ---------- pedidos da instalação ----------
def test_request_signature_window_and_binding(inst):
    req = build_request(inst, "activate", T0, code="psa_x")
    body = verify_request(req, T0 + timedelta(minutes=1))
    assert body["typ"] == "activate" and body["code"] == "psa_x" and body["installation_id"] == inst.installation_id
    assert verify_request(req, T0, expected_public_key=inst.public_b64)["nonce"] == body["nonce"]
    with pytest.raises(RequestError, match="janela"):
        verify_request(req, T0 + timedelta(minutes=6))
    with pytest.raises(RequestError, match="janela"):
        verify_request(req, T0 - timedelta(minutes=6))
    with pytest.raises(RequestError, match="cadastrada"):
        verify_request(req, T0, expected_public_key=Installation.create().public_b64)
    prefix, payload, sig = req.split(".")
    with pytest.raises(RequestError):
        verify_request(f"{prefix}.{b64e(b64d(payload).replace(b'psa_x', b'psa_y'))}.{sig}", T0)
    assert len({verify_request(build_request(inst, "renew", T0), T0)["nonce"] for _ in range(20)}) == 20      # nonces únicos


def test_request_with_someone_elses_public_key_but_claimed_id_is_refused(inst):
    import json

    from promptshield_licensing.crypto import sign_blob
    attacker = Installation.create()
    payload = {"v": 1, "typ": "renew", "installation_id": inst.installation_id, "public_key": attacker.public_b64,
               "timestamp": T0.strftime("%Y-%m-%dT%H:%M:%SZ"), "nonce": "abcdefghijkl"}
    forged = sign_blob(attacker.private, "pr1", json.dumps(payload).encode())
    with pytest.raises(RequestError, match="identificador"):
        verify_request(forged, T0)


# ---------- estados ----------
def st(vendor, inst, now, issued=T0, **kw):
    _, auth = issue(vendor, inst, now=issued)
    return evaluate(auth, now, **kw)


def test_states_follow_the_contract_table(vendor, inst):
    assert evaluate(None, T0).state == State.NAO_ATIVADO and not evaluate(None, T0).inspecting and not evaluate(None, T0).can_enroll
    ok = st(vendor, inst, T0 + timedelta(hours=1), last_success=T0)
    assert (ok.state, ok.can_enroll, ok.inspecting, ok.max_devices) == (State.ATIVO, True, True, 100)
    # falhou a renovação e já passou mais de 1,5 período: sem contato, mas tudo funciona
    nc = st(vendor, inst, T0 + timedelta(days=3), last_success=T0, last_attempt_failed=True)
    assert (nc.state, nc.can_enroll, nc.inspecting) == (State.SEM_CONTATO, True, True) and nc.days_left == 4
    # falha recente (dentro de 1,5 período): ainda ativo, sem alarme
    assert st(vendor, inst, T0 + timedelta(hours=20), last_success=T0, last_attempt_failed=True).state == State.ATIVO
    # a autorização local venceu sem renovar: expirado, mas a inspeção continua
    ex = st(vendor, inst, T0 + timedelta(days=8), last_success=T0, last_attempt_failed=True)
    assert (ex.state, ex.can_enroll, ex.inspecting) == (State.EXPIRADO, False, True)
    # contrato venceu, dentro da tolerância
    late = END + timedelta(days=2)
    _, a = issue(vendor, inst, now=late - timedelta(hours=1))
    tol = evaluate(a, late)
    assert (tol.state, tol.can_enroll, tol.inspecting, tol.days_left) == (State.EM_TOLERANCIA, True, True, 13)
    # depois da tolerância
    after = evaluate(a, END + timedelta(days=16))
    assert after.state == State.EXPIRADO and not after.can_enroll and after.inspecting


def test_closed_contract_applies_the_contracted_policy(vendor, inst):
    _, stop = issue(vendor, inst, status="closed", on_end="stop_inspection")
    _, keep = issue(vendor, inst, status="closed", on_end="keep_inspection")
    s, k = evaluate(stop, T0), evaluate(keep, T0)
    assert (s.state, s.can_enroll, s.inspecting) == (State.ENCERRADO, False, False) and "PARADA" in s.message
    assert (k.state, k.can_enroll, k.inspecting) == (State.ENCERRADO, False, True) and "continua" in k.message


def test_closed_wins_over_every_other_state(vendor, inst):
    _, closed = issue(vendor, inst, status="closed")
    assert evaluate(closed, T0 + timedelta(days=900), last_attempt_failed=True).state == State.ENCERRADO


# ---------- falta de validação: aviso ao cliente (10 dias) e suspensão (21 dias) ----------
WEEK = dict(renew_after_hours=168, warn_after_days=10, suspend_after_days=21, validity=timedelta(days=28))


def weekly(vendor, inst, now, issued=T0, **over):
    _, auth = issue(vendor, inst, now=issued, **{**WEEK, **over})
    return evaluate(auth, now)


def test_silence_timeline_vendor_sees_it_first_then_the_customer_then_suspension(vendor, inst):
    due = T0 + timedelta(days=7)                       # aqui a validação seguinte deveria ter acontecido
    assert weekly(vendor, inst, T0 + timedelta(days=6)).state == State.ATIVO
    first_miss = weekly(vendor, inst, due + timedelta(hours=1))
    assert first_miss.state == State.ATIVO and "ativa" in first_miss.message             # o cliente NÃO é avisado ainda (quem vê é o fornecedor)
    assert weekly(vendor, inst, due + timedelta(days=9, hours=23)).state == State.ATIVO
    warn = weekly(vendor, inst, due + timedelta(days=10))
    assert (warn.state, warn.can_enroll, warn.inspecting) == (State.SEM_CONTATO, True, True) and warn.days_left == 11
    assert "há 10 dia(s)" in warn.message and "suspensa em 11 dia(s)" in warn.message
    assert weekly(vendor, inst, due + timedelta(days=20, hours=23)).state == State.SEM_CONTATO
    stop = weekly(vendor, inst, due + timedelta(days=21))
    assert (stop.state, stop.can_enroll, stop.inspecting) == (State.SUSPENSO, False, False) and "PARADA" in stop.message and "Volta sozinha" in stop.message
    assert weekly(vendor, inst, due + timedelta(days=60)).state == State.SUSPENSO      # nada o "expira" para um estado mais brando


def test_a_successful_validation_heals_the_suspension_by_itself(vendor, inst):
    now = T0 + timedelta(days=40)
    assert weekly(vendor, inst, now).state == State.SUSPENSO
    healed = weekly(vendor, inst, now, issued=now)                                         # a autorização nova traz `issued_at` novo
    assert healed.state == State.ATIVO and healed.inspecting and healed.can_enroll


def test_closed_still_wins_and_old_authorizations_keep_the_old_rule(vendor, inst):
    _, closed = issue(vendor, inst, status="closed", **WEEK)
    assert evaluate(closed, T0 + timedelta(days=90)).state == State.ENCERRADO
    _, old = issue(vendor, inst)                                                           # sem os campos novos: regra antiga (1,5 período, 7 dias)
    assert old.warn_after_days is None and old.suspend_after_days is None
    assert evaluate(old, T0 + timedelta(days=3), last_success=T0, last_attempt_failed=True).state == State.SEM_CONTATO
    assert evaluate(old, T0 + timedelta(days=30), last_attempt_failed=True).state == State.EXPIRADO      # e a inspeção continua (não é suspensão)


def test_contract_end_rules_are_untouched_by_the_silence_rule(vendor, inst):
    late = END + timedelta(days=2)
    _, a = issue(vendor, inst, now=late - timedelta(hours=1), **WEEK)
    assert evaluate(a, late).state == State.EM_TOLERANCIA                                  # contrato vencido, validando em dia
    _, b = issue(vendor, inst, now=END - timedelta(days=1), **WEEK)
    assert evaluate(b, END + timedelta(days=17)).state in (State.EXPIRADO, State.SUSPENSO)


def test_silence_days_are_signed_and_validated(vendor, inst):
    token, auth = issue(vendor, inst, **WEEK)
    ok = verify_authorization(token, vendor.public_key(), inst.installation_id, T0)
    assert (ok.warn_after_days, ok.suspend_after_days) == (10, 21)
    forged = token.replace(token.split(".")[1], token.split(".")[1][:-4] + "AAAA")      # mexer no conteúdo invalida a assinatura
    with pytest.raises(AuthorizationError):
        verify_authorization(forged, vendor.public_key(), inst.installation_id, T0)
    for bad in ({"warn_after_days": 21, "suspend_after_days": 21}, {"warn_after_days": 30, "suspend_after_days": 10},
                {"warn_after_days": 0}, {"suspend_after_days": 400}, {"warn_after_days": True}):
        with pytest.raises(AuthorizationError):
            issue(vendor, inst, **{**WEEK, **bad})
    only_warn, _ = issue(vendor, inst, renew_after_hours=168, warn_after_days=10, validity=timedelta(days=28))      # só aviso, sem suspensão
    a = verify_authorization(only_warn, vendor.public_key(), inst.installation_id, T0)
    assert evaluate(a, T0 + timedelta(days=20)).state == State.SEM_CONTATO and evaluate(a, T0 + timedelta(days=20)).days_left is None
    expired = evaluate(a, T0 + timedelta(days=60))                                                 # sem suspensão configurada: vale a regra antiga (expirado, inspeção continua)
    assert expired.state == State.EXPIRADO and expired.inspecting


# ---------- assinatura de pacotes ----------
def test_package_signature_binds_version_hash_and_product(vendor, tmp_path):
    from promptshield_licensing import sha256_file, sign_package, verify_package
    f = tmp_path / "pkg.zip"
    f.write_bytes(b"conteudo sintetico")
    digest = sha256_file(f)
    assert digest == __import__("hashlib").sha256(b"conteudo sintetico").hexdigest()
    sig = sign_package(vendor, "0.4.0", digest)
    pub = vendor.public_key()
    assert verify_package(pub, "0.4.0", digest, sig)
    assert not verify_package(pub, "0.4.1", digest, sig) and not verify_package(pub, "0.4.0", "0" * 64, sig)           # versão ou conteúdo trocado
    assert not verify_package(generate_signing_key().public_key(), "0.4.0", digest, sig)                              # outra chave
    assert not verify_package(pub, "0.4.0", digest, "não é base64!!") and not verify_package(pub, "0.4.0", digest, "")
