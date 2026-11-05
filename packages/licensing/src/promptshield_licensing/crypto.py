"""Ed25519: geração, serialização e envelope assinado. Usa a biblioteca `cryptography`; nada de criptografia escrita à mão."""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class SignatureError(Exception):
    """Assinatura ausente, malformada ou que não confere."""


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64d(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise SignatureError("base64 inválido") from exc


def generate_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def load_private_key(data: str | bytes) -> Ed25519PrivateKey:
    """Aceita PEM ou o mesmo PEM em base64 (formato para variável de ambiente, sem quebras de linha)."""
    raw = data.encode() if isinstance(data, str) else data
    if not raw.lstrip().startswith(b"-----BEGIN"):
        try:
            raw = base64.b64decode(raw, validate=False)
        except ValueError as exc:
            raise SignatureError("chave privada ilegível") from exc
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except (ValueError, TypeError) as exc:
        raise SignatureError("chave privada ilegível") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SignatureError("a chave precisa ser Ed25519")
    return key


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return b64e(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def load_public_key(text: str) -> Ed25519PublicKey:
    """Aceita os 32 bytes em base64 urlsafe (formato do produto) ou PEM."""
    t = text.strip()
    try:
        if t.startswith("-----BEGIN"):
            key = serialization.load_pem_public_key(t.encode())
            if isinstance(key, Ed25519PublicKey):
                return key
            raise SignatureError("a chave pública precisa ser Ed25519")
        return Ed25519PublicKey.from_public_bytes(b64d(t))
    except (ValueError, TypeError) as exc:
        raise SignatureError("chave pública ilegível") from exc


def fingerprint(pub: Ed25519PublicKey | str) -> str:
    """Identificador estável de uma chave pública (32 caracteres hexadecimais do SHA-256 dos 32 bytes)."""
    raw = b64d(pub) if isinstance(pub, str) else pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:32]


def sign_blob(key: Ed25519PrivateKey, prefix: str, payload: bytes) -> str:
    """`prefix.payload.assinatura`. A assinatura cobre o prefixo (separação de domínio: um pedido nunca vale como autorização)."""
    sig = key.sign(prefix.encode() + b"\n" + payload)
    return f"{prefix}.{b64e(payload)}.{b64e(sig)}"


def verify_blob(pub: Ed25519PublicKey, prefix: str, token: str) -> bytes:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != prefix:
        raise SignatureError("formato inválido")
    payload, sig = b64d(parts[1]), b64d(parts[2])
    try:
        pub.verify(sig, prefix.encode() + b"\n" + payload)
    except InvalidSignature as exc:
        raise SignatureError("assinatura não confere") from exc
    return payload


@dataclass
class Installation:
    """Identidade criptográfica de uma instalação (par de chaves gerado na própria máquina; a privada nunca sai dela)."""

    private: Ed25519PrivateKey

    @classmethod
    def create(cls) -> "Installation":
        return cls(generate_signing_key())

    @property
    def public_b64(self) -> str:
        return public_key_b64(self.private)

    @property
    def installation_id(self) -> str:
        return fingerprint(self.public_b64)

    def pem(self) -> bytes:
        return private_pem(self.private)
