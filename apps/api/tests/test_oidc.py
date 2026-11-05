"""Verificação de token do console, sem banco: mock e OIDC com chave RSA gerada no teste."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import security
from app.config import settings


@pytest.fixture(autouse=True)
def _restore():
    keep = (settings.oidc_mode, settings.oidc_mock_secret, settings.oidc_issuer, settings.oidc_audience)
    yield
    settings.oidc_mode, settings.oidc_mock_secret, settings.oidc_issuer, settings.oidc_audience = keep
    security.set_key_provider(None)


def test_off_mode_rejects_everything():
    settings.oidc_mode = "off"
    with pytest.raises(HTTPException) as e:
        security.verify_token("qualquer")
    assert e.value.status_code == 401


def test_mock_roundtrip_and_tamper():
    settings.oidc_mode, settings.oidc_mock_secret = "mock", "s" * 40
    tok = security.issue_mock_token("a@b.example.com")
    assert security.verify_token(tok)["email"] == "a@b.example.com"
    with pytest.raises(HTTPException):
        security.verify_token(tok[:-3] + "abc")
    with pytest.raises(HTTPException):
        security.verify_token(security.issue_mock_token("a@b.example.com", ttl_seconds=-10))


class _Static(security.KeyProvider):
    def __init__(self, key):
        self.key = key

    def key_for(self, token):
        return self.key, ["RS256"]


def _rs_token(priv, **over):
    now = int(time.time())
    claims = {"iss": "https://idp.example.test", "aud": "console", "sub": "u1", "email": "x@y.example.com",
              "email_verified": True, "iat": now, "exp": now + 60, **over}
    return jwt.encode(claims, priv, algorithm="RS256")


def test_oidc_rs256_checks_signature_issuer_and_audience():
    priv, other = rsa.generate_private_key(65537, 2048), rsa.generate_private_key(65537, 2048)
    settings.oidc_mode, settings.oidc_issuer, settings.oidc_audience = "oidc", "https://idp.example.test", "console"
    security.set_key_provider(_Static(priv.public_key()))
    assert security.verify_token(_rs_token(priv))["sub"] == "u1"
    for bad in (_rs_token(other), _rs_token(priv, iss="https://outro.test"), _rs_token(priv, aud="outro"), _rs_token(priv, exp=1)):
        with pytest.raises(HTTPException):
            security.verify_token(bad)


def test_hs256_token_cannot_be_used_as_rs256_confusion():
    priv = rsa.generate_private_key(65537, 2048)
    settings.oidc_mode, settings.oidc_issuer, settings.oidc_audience = "oidc", "https://idp.example.test", "console"
    security.set_key_provider(_Static(priv.public_key()))
    forged = jwt.encode({"iss": "https://idp.example.test", "aud": "console", "sub": "u", "exp": int(time.time()) + 60},
                        "segredo-simetrico-qualquer-com-32-bytes!!", algorithm="HS256")
    with pytest.raises(HTTPException):
        security.verify_token(forged)
