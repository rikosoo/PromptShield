"""Senha, TOTP (vetores oficiais da RFC 6238), sessão assinada e limite de tentativas do painel. Sem banco."""
import base64
import time

import pytest

from lic_service import panel_auth as pa
from lic_service.config import settings

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()          # a chave de teste da RFC 6238 (SHA-1)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "panel_secret", "s" * 40)
    pa.reset_limits()


@pytest.mark.parametrize("when,expected", [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"),
                                           (2000000000, "69279037"), (20000000000, "65353130")])
def test_totp_matches_the_official_rfc_6238_vectors(when, expected):
    assert pa.totp_code(RFC_SECRET, when // 30) == expected[-6:]          # os vetores da RFC têm 8 dígitos; o painel usa os 6 últimos


def test_totp_window_replay_and_garbage():
    now = 1234567890.0
    step = int(now // 30)
    code = pa.totp_code(RFC_SECRET, step)
    assert pa.verify_totp(RFC_SECRET, code, now) == step
    assert pa.verify_totp(RFC_SECRET, pa.totp_code(RFC_SECRET, step - 1), now) == step - 1          # relógio um pouco atrasado
    assert pa.verify_totp(RFC_SECRET, pa.totp_code(RFC_SECRET, step + 1), now) == step + 1
    assert pa.verify_totp(RFC_SECRET, pa.totp_code(RFC_SECRET, step - 2), now) is None              # fora da janela
    assert pa.verify_totp(RFC_SECRET, code, now, last_step=step) is None                           # o mesmo código não vale duas vezes
    assert pa.verify_totp(RFC_SECRET, f"{code[:3]} {code[3:]}", now) == step                        # espaço no meio é tolerado
    for bad in ("", "12345", "1234567", "abcdef", "000000" if code != "000000" else "111111"):
        assert pa.verify_totp(RFC_SECRET, bad, now) is None


def test_totp_secret_is_stored_encrypted_and_new_secrets_are_random():
    s1, s2 = pa.new_totp_secret(), pa.new_totp_secret()
    assert s1 != s2 and len(s1) == 32
    enc = pa.encrypt_secret(s1)
    assert s1 not in enc and pa.decrypt_secret(enc) == s1
    assert pa.decrypt_secret("lixo") is None
    assert pa.otpauth_uri("a@b.example", s1).startswith("otpauth://totp/PromptShield%20Licencas:a%40b.example?secret=")


def test_vendor_password_policy_is_stricter_than_the_console_one():
    assert pa.policy_errors("Teste-PS-2026!") == []
    assert "pelo menos 12" in " ".join(pa.policy_errors("Abcdef1!"))            # 8 caracteres bastam no console do cliente, não aqui
    assert pa.policy_errors("abcdefghijkl") == ["uma letra maiúscula", "um número", "um caractere especial"]


def test_password_hash_roundtrip_and_never_raises():
    h = pa.hash_password("Teste-PS-2026!")
    assert h.startswith("scrypt$15$8$1$") and "Teste" not in h and h != pa.hash_password("Teste-PS-2026!")
    assert pa.verify_password("Teste-PS-2026!", h) and not pa.verify_password("teste-ps-2026!", h)
    assert all(pa.verify_password("x", bad) is False for bad in (None, "", "lixo", "md5$1$2$3$4$5"))


def test_session_cookie_is_signed_expires_and_dies_with_the_secret(monkeypatch):
    cookie, csrf = pa.make_session("admin-1", 3, now=1000.0)
    data = pa.read_session(cookie, now=1500.0)
    assert data and data["a"] == "admin-1" and data["pv"] == 3 and data["csrf"] == csrf
    assert pa.read_session(cookie, now=1000.0 + settings.panel_session_hours * 3600 + 1) is None          # expirou
    payload, sig = cookie.split(".")
    forged = pa._b64(b'{"a":"admin-1","pv":3,"csrf":"x","exp":9999999999}') + "." + sig
    assert pa.read_session(forged, now=1500.0) is None                                                     # conteúdo trocado: assinatura não confere
    assert pa.read_session(payload + ".AAAA", now=1500.0) is None and pa.read_session("lixo", now=1500.0) is None and pa.read_session(None) is None
    monkeypatch.setattr(settings, "panel_secret", "outro-segredo-com-mais-de-32-caracteres")
    assert pa.read_session(cookie, now=1500.0) is None                                                     # trocar o segredo derruba tudo


def test_login_rate_limit():
    assert [pa.too_many("k", 3, now=100.0 + i) for i in range(5)] == [False, False, False, True, True]
    assert pa.too_many("k", 3, now=200.0) is False                                                         # passou 1 minuto
    assert time.monotonic() > 0
