"""Licenciamento do PromptShield: autorizações assinadas (Ed25519), identidade da instalação e máquina de estados.

Biblioteca pura (sem rede, sem banco, sem web). Usada pelo serviço de licenças (do fornecedor) e pelo servidor do cliente."""
from .authorization import Authorization, AuthorizationError, issue_authorization, verify_authorization
from .crypto import (
    Installation,
    SignatureError,
    b64d,
    b64e,
    fingerprint,
    generate_signing_key,
    load_private_key,
    load_public_key,
    public_key_b64,
    sign_blob,
    verify_blob,
)
from .requests import RequestError, build_request, verify_request
from .states import LicenseState, State, evaluate

__all__ = [
    "Authorization", "AuthorizationError", "Installation", "LicenseState", "RequestError", "SignatureError", "State", "b64d", "b64e",
    "build_request", "evaluate", "fingerprint", "generate_signing_key", "issue_authorization", "load_private_key", "load_public_key",
    "public_key_b64", "sign_blob", "verify_authorization", "verify_blob", "verify_request",
]
