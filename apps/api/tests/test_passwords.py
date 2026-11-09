"""Política, hash e senha temporária (sem banco)."""
import pytest

from app import passwords as pw


@pytest.mark.parametrize("ok", ["Abcdef1!", "Teste-PS-2026!", "x" * 3 + "Y" * 3 + "9!", "Senha@123", "Ação#Forte9ç"])
def test_valid_passwords(ok):
    assert pw.policy_errors(ok) == []


@pytest.mark.parametrize("bad,missing", [
    ("123456", ["pelo menos 8", "minúscula", "maiúscula", "especial"]),
    ("abcdefgh", ["maiúscula", "número", "especial"]),
    ("ABCDEFG1!", ["minúscula"]),
    ("Abcdefg1", ["especial"]),
    ("Abcdefg!", ["número"]),
    ("Ab1!", ["pelo menos 8"]),
    ("Abcdef1 ", ["especial"]),             # espaço não conta como caractere especial
    ("A" * 129 + "b1!", ["no máximo 128"]),
])
def test_invalid_passwords_say_what_is_missing(bad, missing):
    msg = pw.policy_message(bad)
    assert msg is not None and all(m in msg for m in missing)


def test_hash_verify_roundtrip_salt_and_format():
    h1, h2 = pw.hash_password("Teste-PS-2026!"), pw.hash_password("Teste-PS-2026!")
    assert h1 != h2 and h1.startswith("scrypt$15$8$1$") and "Teste" not in h1       # sal próprio; a senha não aparece
    assert pw.verify_password("Teste-PS-2026!", h1) and pw.verify_password("Teste-PS-2026!", h2)
    assert not pw.verify_password("teste-ps-2026!", h1) and not pw.verify_password("", h1)


def test_verify_never_raises_on_garbage_and_missing():
    for stored in (None, "", "lixo", "scrypt$x$y", "md5$1$2$3$4$5", "scrypt$15$8$1$@@$@@"):
        assert pw.verify_password("Abcdef1!", stored) is False


def test_unicode_is_normalized():
    assert pw.verify_password("Ação#Forte9", pw.hash_password("Ação#Forte9"))
    assert pw.verify_password("Ação#Forte9", pw.hash_password("Ação#Forte9"))     # mesma senha, composta ou decomposta


def test_temporary_password_meets_the_policy_and_is_random():
    seen = {pw.generate_temporary() for _ in range(200)}
    assert len(seen) == 200
    assert all(pw.policy_errors(p) == [] and len(p) == 14 for p in seen)
    assert not any(set(p) & set("0O1lI") for p in seen)
