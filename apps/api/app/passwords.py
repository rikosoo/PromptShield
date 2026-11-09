"""Senhas do console: política, hash (scrypt, só biblioteca padrão) e senha temporária.

Política decidida pelo dono (2026-11-09): 8 ou mais caracteres, com letra minúscula, letra maiúscula, número e caractere especial.
Limite honesto: essa regra aceita senhas fracas como «Senha@123»; não há lista de senhas comuns (decisão pendente, ver docs/decisoes.md).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata

MIN_LENGTH, MAX_LENGTH = 8, 128
SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P = 15, 8, 1          # 32 MiB e cerca de 0,1 s por verificação; os parâmetros vão dentro do hash e podem subir depois
_MAXMEM = 128 * 1024 * 1024
_SPECIAL = "!@#$%&*()-_=+[]{};:,.?/"


def policy_errors(password: str) -> list[str]:
    """O que falta para a senha valer (lista vazia = vale). Mensagens em português para mostrar ao usuário."""
    out = []
    if len(password) < MIN_LENGTH:
        out.append(f"pelo menos {MIN_LENGTH} caracteres")
    if len(password) > MAX_LENGTH:
        out.append(f"no máximo {MAX_LENGTH} caracteres")
    if not any(c.islower() for c in password):
        out.append("uma letra minúscula")
    if not any(c.isupper() for c in password):
        out.append("uma letra maiúscula")
    if not any(c.isdigit() for c in password):
        out.append("um número")
    if not any(not c.isalnum() and not c.isspace() for c in password):
        out.append("um caractere especial (como ! @ # $ %)")
    return out


def policy_message(password: str) -> str | None:
    errs = policy_errors(password)
    return None if not errs else "a senha precisa ter: " + "; ".join(errs)


def _norm(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def _derive(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(_norm(password), salt=salt, n=2**log_n, r=r, p=p, maxmem=_MAXMEM, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = _derive(password, salt, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")   # noqa: E731
    return f"scrypt${SCRYPT_LOG_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Compara em tempo constante. `stored` vazio ou malformado dá False (e gasta o mesmo tempo de uma conta real)."""
    try:
        if not stored:
            raise ValueError
        algo, log_n, r, p, salt, want = stored.split("$")
        if algo != "scrypt":
            raise ValueError
        got = _derive(password, base64.b64decode(salt), int(log_n), int(r), int(p))
        return hmac.compare_digest(got, base64.b64decode(want))
    except (ValueError, TypeError):
        _derive(password, b"\x00" * 16, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P)     # iguala o tempo: não revela se a conta existe
        return False


def generate_temporary() -> str:
    """Senha temporária que já cumpre a política (14 caracteres, sem letras que se confundem). Mostrada uma única vez ao administrador."""
    lower, upper, digit = "abcdefghijkmnopqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789"
    chars = [secrets.choice(lower), secrets.choice(upper), secrets.choice(digit), secrets.choice(_SPECIAL)]
    pool = lower + upper + digit + _SPECIAL
    chars += [secrets.choice(pool) for _ in range(10)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
