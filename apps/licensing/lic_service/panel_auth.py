"""Autenticação do painel do fornecedor: senha (scrypt), código de 6 dígitos de aplicativo autenticador (TOTP, RFC 6238), sessão assinada e CSRF.

Por que tanto cuidado: quem entra no painel pode encerrar e suspender TODOS os clientes (e, nas etapas seguintes, publicar versões). Por isso a senha do
fornecedor é mais exigente que a do console do cliente (12+ caracteres), o código de 6 dígitos é exigido por padrão e o mesmo código não vale duas vezes.
Só biblioteca padrão e `cryptography` (nada de criptografia escrita à mão além do TOTP, que é um padrão de 20 linhas).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import unicodedata
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from lic_service import ratelimit
from lic_service.config import settings

MIN_LENGTH, MAX_LENGTH = 12, 128
SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P = 15, 8, 1
_MAXMEM = 128 * 1024 * 1024
TOTP_STEP, TOTP_DIGITS, TOTP_WINDOW = 30, 6, 1


# ---------------- senha ----------------
def policy_errors(password: str) -> list[str]:
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
        out.append("um caractere especial")
    return out


def _norm(p: str) -> bytes:
    return unicodedata.normalize("NFKC", p).encode("utf-8")


def _derive(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(_norm(password), salt=salt, n=2**log_n, r=r, p=p, maxmem=_MAXMEM, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    b64 = lambda b: base64.b64encode(b).decode("ascii")   # noqa: E731
    return f"scrypt${SCRYPT_LOG_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(_derive(password, salt, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P))}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        if not stored:
            raise ValueError
        algo, log_n, r, p, salt, want = stored.split("$")
        if algo != "scrypt":
            raise ValueError
        return hmac.compare_digest(_derive(password, base64.b64decode(salt), int(log_n), int(r), int(p)), base64.b64decode(want))
    except (ValueError, TypeError):
        _derive(password, b"\x00" * 16, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P)      # gasta o mesmo tempo: não revela se a conta existe
        return False


# ---------------- chaves derivadas do segredo do painel ----------------
def _derived(info: bytes) -> bytes:
    secret = (settings.panel_secret or "").encode()
    if len(secret) < 32:
        raise RuntimeError("PANEL_SECRET ausente ou curto")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret)


def encrypt_secret(plain: str) -> str:
    return Fernet(base64.urlsafe_b64encode(_derived(b"lic-panel/totp"))).encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return Fernet(base64.urlsafe_b64encode(_derived(b"lic-panel/totp"))).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------- TOTP (RFC 6238: HMAC-SHA1, passo de 30 s, 6 dígitos) ----------------
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = h[-1] & 0x0F
    value = (struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % 10**TOTP_DIGITS
    return f"{value:0{TOTP_DIGITS}d}"


def verify_totp(secret_b32: str, code: str, now: float | None = None, last_step: int | None = None) -> int | None:
    """Passo aceito (para guardar) ou None. Aceita o passo atual e os vizinhos (relógios levemente diferentes) e recusa passo já usado."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    cur = int((time.time() if now is None else now) // TOTP_STEP)
    for step in range(cur - TOTP_WINDOW, cur + TOTP_WINDOW + 1):
        if hmac.compare_digest(totp_code(secret_b32, step), code) and (last_step is None or step > last_step):
            return step
    return None


def otpauth_uri(email: str, secret_b32: str, issuer: str = "PromptShield Licencas") -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret_b32}&issuer={quote(issuer)}&digits={TOTP_DIGITS}&period={TOTP_STEP}"


# ---------------- sessão assinada (cookie) e CSRF ----------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_payload(obj: dict[str, Any], ttl_seconds: int, purpose: bytes = b"session", now: float | None = None) -> str:
    """`payload.assinatura` (HMAC-SHA256, chave derivada por finalidade). Serve para a sessão e para o aviso de uma vez só."""
    now = time.time() if now is None else now
    payload = _b64(json.dumps({**obj, "exp": int(now + ttl_seconds)}, separators=(",", ":")).encode())
    return f"{payload}.{_b64(hmac.new(_derived(b'lic-panel/' + purpose), payload.encode(), hashlib.sha256).digest())}"


def read_payload(cookie: str | None, purpose: bytes = b"session", now: float | None = None) -> dict[str, Any] | None:
    try:
        payload, sig = (cookie or "").split(".")
        good = _b64(hmac.new(_derived(b"lic-panel/" + purpose), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
        if not isinstance(data, dict) or data.get("exp", 0) < (time.time() if now is None else now):
            return None
        return data
    except (ValueError, TypeError, RuntimeError):
        return None


def make_session(admin_id: str, password_version: int, now: float | None = None) -> tuple[str, str]:
    """(valor do cookie, token CSRF). Trocar a senha (versão) ou o PANEL_SECRET derruba a sessão."""
    csrf = secrets.token_urlsafe(24)
    return sign_payload({"a": admin_id, "pv": password_version, "csrf": csrf}, settings.panel_session_hours * 3600, b"session", now), csrf


def read_session(cookie: str | None, now: float | None = None) -> dict[str, Any] | None:
    return read_payload(cookie, b"session", now)


# ---------------- limite de tentativas de entrada (compartilhado entre processos; veja ratelimit.py) ----------------
def too_many(key: str, per_minute: int, now: float | None = None) -> bool:
    return ratelimit.count(f"panel:{key}", now) > per_minute


def reset_limits() -> None:
    ratelimit.reset()
