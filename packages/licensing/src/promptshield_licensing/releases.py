"""Versões novas: comparação de versão e o AVISO assinado que o serviço do fornecedor entrega junto com a validação.

O aviso diz "existe a versão X (ou o pacote de regras X), com este SHA-256 e este tamanho, e isto é (ou não) uma correção de segurança".
Ele é assinado com a chave do fornecedor (a mesma pinada na instalação) e leva dentro a assinatura do PACOTE (versão + SHA-256), então quem
recebe consegue provar, sem confiar no caminho, que o arquivo que vai baixar é o que o fornecedor publicou. Nada aqui executa nem instala coisa alguma.

Regra de segurança que vale para quem aplica: só se aceita versão MAIOR que a instalada (nunca voltar para uma versão com falha conhecida)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .crypto import SignatureError, sign_blob, verify_blob
from .packages import PACKAGE_PRODUCT, RULES_PRODUCT, verify_package

NOTICE_PREFIX = "pn1"
Kind = Literal["app", "rules"]
PRODUCT_OF: dict[str, str] = {"app": PACKAGE_PRODUCT, "rules": RULES_PRODUCT}
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[.-][A-Za-z][0-9A-Za-z]*)?$")      # sufixo só começa com letra (rc1, beta2)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_NOTES = 1000


FILE_RE = re.compile(r"^promptshield-(?:onprem|rules)-[0-9A-Za-z][0-9A-Za-z.-]{0,60}\.(?:zip|pack)$")


class ReleaseError(Exception):
    pass


def parse_version(v: str) -> tuple:
    """`0.4.0` < `0.4.1` < `0.10.0`; `0.4.0-rc1` vem ANTES de `0.4.0`. Versões como `2026.11.1` (pacote de regras) também servem."""
    if not isinstance(v, str) or not VERSION_RE.match(v):
        raise ReleaseError(f"versão inválida: {v!r}")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*)(?:[.-]([A-Za-z][0-9A-Za-z]*))?$", v)
    nums = tuple(int(x) for x in m.group(1).split("."))          # type: ignore[union-attr]
    nums += (0,) * (4 - len(nums))
    suffix = m.group(2)                                          # type: ignore[union-attr]
    return (nums, 0 if suffix else 1, suffix or "")


def is_newer(candidate: str, installed: str | None) -> bool:
    """Só vale versão MAIOR que a instalada. Sem versão instalada (None), qualquer versão válida vale."""
    if installed is None:
        parse_version(candidate)
        return True
    return parse_version(candidate) > parse_version(installed)


@dataclass(frozen=True)
class ReleaseNotice:
    kind: Kind
    version: str
    sha256: str
    size: int
    security: bool
    notes: str
    published_at: datetime
    package_signature: str           # assinatura do PACOTE (versão + SHA-256), conferida de novo por quem baixa
    file: str


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue_notice(key: Ed25519PrivateKey, *, kind: Kind, version: str, sha256: str, size: int, security: bool, notes: str, published_at: datetime,
                 package_signature: str, file: str) -> str:
    parse_version(version)
    if kind not in PRODUCT_OF or not SHA_RE.match(sha256) or size <= 0:
        raise ReleaseError("aviso inválido (tipo, SHA-256 ou tamanho)")
    claims = {"v": 1, "typ": "release", "product": PRODUCT_OF[kind], "kind": kind, "version": version, "sha256": sha256, "size": int(size), "security": bool(security),
              "notes": notes[:MAX_NOTES], "published_at": _iso(published_at), "package_signature": package_signature, "file": file}
    return sign_blob(key, NOTICE_PREFIX, json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())


def verify_notice(token: str, pub: Ed25519PublicKey) -> ReleaseNotice:
    """Confere a assinatura do aviso E a assinatura do pacote que ele cita. Qualquer divergência vira ReleaseError (e o aviso é ignorado)."""
    try:
        claims: dict[str, Any] = json.loads(verify_blob(pub, NOTICE_PREFIX, token))
    except (SignatureError, ValueError) as exc:
        raise ReleaseError("aviso com assinatura inválida") from exc
    try:
        kind = claims["kind"]
        if claims.get("typ") != "release" or claims.get("v") != 1 or kind not in PRODUCT_OF or claims.get("product") != PRODUCT_OF[kind]:
            raise ReleaseError("não é um aviso de versão deste produto")
        version, sha, size = str(claims["version"]), str(claims["sha256"]), int(claims["size"])
        parse_version(version)
        if not SHA_RE.match(sha) or size <= 0:
            raise ReleaseError("SHA-256 ou tamanho inválido")
        if not FILE_RE.fullmatch(str(claims["file"])):                 # vira caminho no disco do cliente: nada de barra, "..", caminho absoluto ou nome estranho
            raise ReleaseError("nome de arquivo inválido")
        n = ReleaseNotice(kind, version, sha, size, bool(claims["security"]), str(claims.get("notes", ""))[:MAX_NOTES],
                          datetime.strptime(claims["published_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), str(claims["package_signature"]), str(claims["file"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseError("aviso com campos faltando ou inválidos") from exc
    if not verify_package(pub, n.version, n.sha256, n.package_signature, PRODUCT_OF[n.kind]):
        raise ReleaseError("a assinatura do pacote citada no aviso não confere")
    return n


def notice_to_dict(n: ReleaseNotice) -> dict[str, Any]:
    d = asdict(n)
    d["published_at"] = _iso(n.published_at)
    return d


# ---------------------------------------------------------------- pacote de regras: o envelope assinado
RULEPACK_PREFIX = "pk1"
MAX_RULEPACK_BYTES = 2 * 1024 * 1024


def sign_rulepack(key: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    """Assina o conteúdo do pacote de regras (JSON canônico). O arquivo distribuído é só este texto: `pk1.<conteúdo>.<assinatura>`."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_RULEPACK_BYTES:
        raise ReleaseError("pacote de regras grande demais")
    return sign_blob(key, RULEPACK_PREFIX, raw)


def verify_rulepack(token: str, pub: Ed25519PublicKey) -> dict[str, Any]:
    """Confere a assinatura e devolve o conteúdo (ainda NÃO validado como regras: quem valida é promptshield_detection.rulepack)."""
    if len(token) > MAX_RULEPACK_BYTES * 2:
        raise ReleaseError("pacote de regras grande demais")
    try:
        payload = json.loads(verify_blob(pub, RULEPACK_PREFIX, token.strip()))
    except (SignatureError, ValueError) as exc:
        raise ReleaseError("pacote de regras com assinatura inválida") from exc
    if not isinstance(payload, dict):
        raise ReleaseError("conteúdo do pacote de regras inválido")
    return payload
