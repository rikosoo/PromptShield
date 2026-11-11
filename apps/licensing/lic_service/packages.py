"""Pacotes de instalação que o painel entrega ao cliente: lê a pasta, confere a assinatura de cada um e só serve o que está na lista.

Cada pacote `promptshield-onprem-<versão>.zip` tem ao lado `<mesmo nome>.manifest.json` (versão, SHA-256, tamanho, assinatura) e `<...>.README.md`,
gerados por `infra/release/build_package.py`. O painel NÃO constrói pacotes: constrói-se numa máquina de build e copia-se para a pasta."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from promptshield_licensing import load_private_key, sha256_file, verify_package

from lic_service.config import settings

NAME_RE = re.compile(r"^promptshield-onprem-[0-9A-Za-z][0-9A-Za-z._-]{0,40}\.zip$")


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    size: int
    sha256: str
    built_at: str | None
    signature_ok: bool          # a assinatura do manifesto confere com a chave do fornecedor
    hash_ok: bool               # o arquivo na pasta ainda tem o SHA-256 do manifesto (não foi trocado depois)
    has_readme: bool

    @property
    def trusted(self) -> bool:
        return self.signature_ok and self.hash_ok


def _public_key():
    if not settings.license_signing_key:
        return None
    try:
        return load_private_key(settings.license_signing_key).public_key()
    except Exception:  # noqa: BLE001 - chave ilegível: nenhum pacote é "confiável", e o painel avisa
        return None


def packages_dir() -> Path:
    return Path(settings.packages_dir)


def list_packages(verify_hash: bool = True) -> list[Package]:
    d = packages_dir()
    if not d.is_dir():
        return []
    pub = _public_key()
    out: list[Package] = []
    for zf in sorted(d.glob("promptshield-onprem-*.zip"), reverse=True):
        if not NAME_RE.match(zf.name) or not zf.is_file():
            continue
        try:
            m = json.loads((d / f"{zf.name}.manifest.json").read_text(encoding="utf-8"))
            version, digest, sig = str(m["version"]), str(m["sha256"]), str(m["signature"])
        except (OSError, ValueError, KeyError, TypeError):
            continue                                                  # sem manifesto legível: não é oferecido
        sig_ok = pub is not None and verify_package(pub, version, digest, sig)
        hash_ok = (sha256_file(zf) == digest) if verify_hash else True
        out.append(Package(zf.name, version, zf.stat().st_size, digest, m.get("built_at"), sig_ok, hash_ok, (d / f"{zf.name[:-4]}.README.md").is_file()))
    return out


def find(name: str) -> Package | None:
    """Só devolve um pacote que ESTÁ na lista (nada de montar caminho a partir do que veio na URL)."""
    return next((p for p in list_packages(verify_hash=True) if p.name == name), None)


def file_path(pkg: Package) -> Path:
    return packages_dir() / pkg.name


def readme_text(pkg: Package) -> str | None:
    f = packages_dir() / f"{pkg.name[:-4]}.README.md"
    try:
        return f.read_text(encoding="utf-8") if pkg.has_readme else None
    except OSError:
        return None


def fmt_size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} KB"


def parse_built_at(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None
