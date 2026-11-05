"""Cifra em repouso por tenant.

Hierarquia: ORIGINAL_TEXT_MASTER_KEY (chave mestra, fora do banco) -> chave de dados do tenant (DEK, aleatória, guardada no banco
EMBRULHADA pela chave mestra) -> chaves por finalidade (texto original, segredos de canais) derivadas por HKDF.

- Trocar a chave mestra = reembrulhar as DEKs (`python -m app.cli rewrap-keys`), sem recifrar os dados.
- Apagar o tenant apaga a DEK junto: os textos originais cifrados que sobrarem (por exemplo em um backup) ficam ilegíveis
  sem a chave mestra E sem a DEK de um backup anterior.
- Interino até um KMS: quem tem o banco E a chave mestra lê tudo. A chave mestra NÃO vai no backup do banco (docs/operacao.md).
- Textos cifrados antes desta versão (sem o prefixo `v2.`) continuam legíveis pela derivação antiga.
"""
from __future__ import annotations

import base64
import os
import threading
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import text

from app.config import settings

PREFIX = b"v2."
_cache: dict[uuid.UUID, bytes] = {}
_lock = threading.Lock()


class MasterKeyMissingError(RuntimeError):
    pass


def _master(b64: str | None = None) -> bytes:
    value = b64 if b64 is not None else settings.original_text_master_key
    if not value:
        raise MasterKeyMissingError("ORIGINAL_TEXT_MASTER_KEY não configurada")
    return base64.urlsafe_b64decode(value)


def _hkdf(key: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(key)


def _wrapper(master: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_hkdf(master, b"promptshield/dek-wrap")))


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _dek(tenant_id: uuid.UUID) -> bytes:
    with _lock:
        cached = _cache.get(tenant_id)
    if cached is not None:
        return cached
    from app.db import tenant_session

    wrapper = _wrapper(_master())
    with tenant_session(tenant_id) as s:
        wrapped = s.execute(text("SELECT data_key_wrapped FROM tenant_keys WHERE tenant_id = :i"), {"i": tenant_id}).scalar()
        if wrapped is None:
            # sem corrida: quem perde a inserção lê a chave do vencedor
            s.execute(text("INSERT INTO tenant_keys (tenant_id, data_key_wrapped) VALUES (:i, :w) ON CONFLICT (tenant_id) DO NOTHING"),
                      {"i": tenant_id, "w": wrapper.encrypt(os.urandom(32))})
            wrapped = s.execute(text("SELECT data_key_wrapped FROM tenant_keys WHERE tenant_id = :i"), {"i": tenant_id}).scalar()
    dek = wrapper.decrypt(bytes(wrapped))
    with _lock:
        _cache[tenant_id] = dek
    return dek


def _fernet(tenant_id: uuid.UUID, purpose: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_hkdf(_dek(tenant_id), b"promptshield/" + purpose)))


def _legacy_fernet(tenant_id: uuid.UUID, purpose: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_hkdf(_master(), b"promptshield/" + purpose + b"/" + tenant_id.bytes)))


def _encrypt(tenant_id: uuid.UUID, purpose: bytes, value: str) -> bytes:
    return PREFIX + _fernet(tenant_id, purpose).encrypt(value.encode("utf-8"))


def _decrypt(tenant_id: uuid.UUID, purpose: bytes, blob: bytes) -> str:
    blob = bytes(blob)
    if blob.startswith(PREFIX):
        return _fernet(tenant_id, purpose).decrypt(blob[len(PREFIX):]).decode("utf-8")
    return _legacy_fernet(tenant_id, purpose).decrypt(blob).decode("utf-8")


def encrypt_original(tenant_id: uuid.UUID, text_value: str) -> bytes:
    return _encrypt(tenant_id, b"original", text_value)


def decrypt_original(tenant_id: uuid.UUID, blob: bytes) -> str:
    return _decrypt(tenant_id, b"original", blob)


def encrypt_secret(tenant_id: uuid.UUID, value: str) -> bytes:
    """Segredos e URLs de canais, e o segredo dos inference hooks. Finalidade separada da do texto original."""
    return _encrypt(tenant_id, b"channel-secret", value)


def decrypt_secret(tenant_id: uuid.UUID, blob: bytes) -> str:
    return _decrypt(tenant_id, b"channel-secret", blob)


def rewrap_keys(session, old_master_b64: str, new_master_b64: str) -> int:
    """Troca a chave mestra: desembrulha cada DEK com a antiga e embrulha com a nova. `session` com app.tenant_id por tenant."""
    old, new = _wrapper(_master(old_master_b64)), _wrapper(_master(new_master_b64))
    n = 0
    ids = [r.tenant_id for r in session.execute(text("SELECT tenant_id FROM list_tenant_ids()"))]
    for tid in ids:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        wrapped = session.execute(text("SELECT data_key_wrapped FROM tenant_keys WHERE tenant_id = :i"), {"i": tid}).scalar()
        if wrapped is None:
            continue
        session.execute(text("UPDATE tenant_keys SET data_key_wrapped = :w WHERE tenant_id = :i"),
                        {"w": new.encrypt(old.decrypt(bytes(wrapped))), "i": tid})
        n += 1
    clear_cache()
    return n
