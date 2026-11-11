"""Assinatura dos PACOTES de instalação (o .zip que o fornecedor entrega ao cliente) e das versões.

O que se assina é o SHA-256 do arquivo + versão + produto, com prefixo próprio (separação de domínio: uma assinatura de pacote nunca vale como
autorização nem como pedido). Quem confere é o painel do fornecedor (para não entregar um arquivo adulterado na pasta de pacotes) e, nas etapas
seguintes, o próprio produto do cliente antes de aceitar uma versão nova."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PACKAGE_PRODUCT = "promptshield-onprem"          # o pacote de instalação (aplicação)
RULES_PRODUCT = "promptshield-rules"             # o pacote de regras de detecção (dados). Produto diferente = assinatura diferente: um nunca vale como o outro
_DOMAIN = b"promptshield-package/v1|"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def package_message(version: str, sha256: str, product: str = PACKAGE_PRODUCT) -> bytes:
    return _DOMAIN + f"{product}|{version}|{sha256}".encode()


def sign_package(key: Ed25519PrivateKey, version: str, sha256: str, product: str = PACKAGE_PRODUCT) -> str:
    return base64.b64encode(key.sign(package_message(version, sha256, product))).decode()


def verify_package(pub: Ed25519PublicKey, version: str, sha256: str, signature_b64: str, product: str = PACKAGE_PRODUCT) -> bool:
    try:
        pub.verify(base64.b64decode(signature_b64, validate=True), package_message(version, sha256, product))
        return True
    except (InvalidSignature, ValueError):
        return False
