#!/usr/bin/env python3
"""Constrói o pacote de instalação que o fornecedor entrega ao cliente (promptshield-onprem-<versão>.zip) e o assina.

    LICENSE_SIGNING_KEY=<chave privada> python infra/release/build_package.py --version 0.4.0 --license-url https://licencas.seudominio.com.br --with-images

Roda na SUA máquina de build (com Docker, se usar --with-images), nunca no painel. Saída em --out (padrão dist/packages):
  promptshield-onprem-<v>.zip                o que você manda ao cliente
  promptshield-onprem-<v>.zip.manifest.json  versão, SHA-256, tamanho e assinatura (o painel confere antes de liberar o download)
  promptshield-onprem-<v>.README.md          o LEIA-ME do pacote (o painel mostra)
Copie os três para a pasta de pacotes do servidor do painel (PACKAGES_HOST_DIR).

Sem --with-images o pacote leva as FONTES e o cliente constrói as imagens (precisa de internet): serve para auditoria e para testar.
O zip é reproduzível: mesmo conteúdo e mesma versão dão o mesmo SHA-256."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATES = HERE / "templates"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)?$")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)         # zip reproduzível
SOURCE_DIRS = ("packages", "apps/api", "apps/web", "apps/extension")
SOURCE_EXCLUDE = {"tests", "node_modules", ".next", "__pycache__", ".pytest_cache", "test-results", ".venv", "dist", "playwright-report", ".ruff_cache", "tsconfig.tsbuildinfo"}
EXECUTABLE = {"instalar.sh", "backup.sh"}


class BuildError(Exception):
    pass


def render(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    if left := re.findall(r"\{\{[A-Z_]+\}\}", text):
        raise BuildError(f"marcador sem valor: {sorted(set(left))}")
    return text


def _copy_source(dst: Path, root: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SOURCE_EXCLUDE or n.endswith((".pyc", ".egg-info"))}

    for rel in SOURCE_DIRS:
        src = root / rel
        if src.is_dir():
            shutil.copytree(src, dst / rel, ignore=ignore)


def _images(docker: str, version: str, root: Path, out_dir: Path) -> None:
    """Constrói as imagens do produto e salva tudo (inclusive o PostgreSQL) num único arquivo que o instalador carrega sem internet."""
    # `docker` vem da linha de comando de quem monta o pacote (o fornecedor) e `version` já passou pela expressão regular da versão: sem entrada de terceiros
    run = lambda *a: subprocess.run([docker, *a], cwd=root, check=True)   # noqa: E731, S603
    run("build", "-f", "apps/api/Dockerfile", "-t", f"promptshield/api:{version}", ".")
    run("build", "-t", f"promptshield/web:{version}", "apps/web")
    run("pull", "postgres:16")
    out_dir.mkdir(parents=True, exist_ok=True)
    tar = out_dir / f"promptshield-{version}.tar"
    with open(tar, "wb") as f:
        subprocess.run([docker, "save", f"promptshield/api:{version}", f"promptshield/web:{version}", "postgres:16"], check=True, stdout=f)  # noqa: S603
    import gzip
    with open(tar, "rb") as src, gzip.GzipFile(str(tar) + ".gz", "wb", mtime=0) as dst:
        shutil.copyfileobj(src, dst)
    tar.unlink()


def _checksums(stage: Path) -> str:
    lines = []
    for p in sorted(x for x in stage.rglob("*") if x.is_file() and x.name != "SHA256SUMS"):
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(stage).as_posix()}")
    return "\n".join(lines) + "\n"


def _zip(stage: Path, dest: Path, top: str) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(x for x in stage.rglob("*") if x.is_file()):
            rel = p.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(f"{top}/{rel}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if p.name in EXECUTABLE else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            z.writestr(info, p.read_bytes())


def build(version: str, license_url: str, out: Path, *, signing_key: str, with_images: bool = False, with_source: bool | None = None,
          docker: str = "docker", root: Path = ROOT, allow_http: bool = False) -> dict[str, str]:
    from promptshield_licensing import fingerprint, load_private_key, public_key_b64, sha256_file, sign_package

    if not VERSION_RE.match(version):
        raise BuildError(f"versão inválida: {version!r} (use algo como 0.4.0)")
    u = urlparse(license_url)
    if not u.hostname or u.scheme not in ("https", "http") or (u.scheme == "http" and not allow_http):
        raise BuildError("a URL do serviço de licenças precisa ser https (http só com --allow-http, para teste)")
    if not signing_key:
        raise BuildError("sem chave de assinatura: defina LICENSE_SIGNING_KEY")
    try:
        key = load_private_key(signing_key)
    except Exception as exc:  # noqa: BLE001
        raise BuildError("a chave de assinatura é ilegível") from exc
    pub = public_key_b64(key)
    values = {"VERSION": version, "LICENSE_URL": license_url.rstrip("/"), "LICENSE_HOST": u.hostname, "PUBLIC_KEY": pub}
    include_source = (not with_images) if with_source is None else with_source
    top = f"promptshield-onprem-{version}"
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ps-pkg-") as tmp:
        stage = Path(tmp) / top
        stage.mkdir()
        for name in ("docker-compose.yml", "env.example", "instalar.sh", "instalar.ps1", "backup.sh", "LEIA-ME.md"):
            (stage / name).write_text(render((TEMPLATES / name).read_text(encoding="utf-8"), values), encoding="utf-8", newline="\n")
        (stage / "VERSION").write_text(version + "\n")
        (stage / "licenca").mkdir()
        (stage / "licenca" / "CHAVE_PUBLICA.txt").write_text(f"{pub}\n# identificador da chave: {fingerprint(pub)}\n")
        if with_images:
            _images(docker, version, root, stage / "imagens")
        if include_source:
            _copy_source(stage / "fontes", root)
        (stage / "SHA256SUMS").write_text(_checksums(stage))
        readme = (stage / "LEIA-ME.md").read_text(encoding="utf-8")
        zip_path = out / f"{top}.zip"
        _zip(stage, zip_path, top)

    digest = sha256_file(zip_path)
    manifest = {"product": "promptshield-onprem", "version": version, "file": zip_path.name, "sha256": digest, "size": zip_path.stat().st_size,
                "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "key_id": fingerprint(pub), "with_images": with_images,
                "with_source": include_source, "signature": sign_package(key, version, digest)}
    (out / f"{zip_path.name}.manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / f"{top}.README.md").write_text(readme, encoding="utf-8")
    return {"zip": str(zip_path), "sha256": digest, "version": version, "size": str(manifest["size"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--license-url", required=True, help="endereço https do SEU serviço de licenças (vai no pacote; o cliente precisa alcançá-lo)")
    ap.add_argument("--out", default=str(ROOT / "dist" / "packages"))
    ap.add_argument("--with-images", action="store_true", help="constrói e inclui as imagens Docker (precisa de Docker nesta máquina)")
    ap.add_argument("--with-source", dest="with_source", action="store_true", default=None, help="inclui as fontes (padrão quando não há imagens)")
    ap.add_argument("--no-source", dest="with_source", action="store_false", help="não inclui as fontes (para testar a estrutura)")
    ap.add_argument("--docker", default="docker")
    ap.add_argument("--allow-http", action="store_true", help="aceita URL http (só teste)")
    a = ap.parse_args(argv)
    try:
        res = build(a.version, a.license_url, Path(a.out), signing_key=os.environ.get("LICENSE_SIGNING_KEY", ""), with_images=a.with_images,
                    with_source=a.with_source, docker=a.docker, allow_http=a.allow_http)
    except BuildError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(f"Pacote: {res['zip']}\nSHA-256: {res['sha256']}   (envie ao cliente junto com o pacote)\nTamanho: {int(res['size']) / 1_048_576:.1f} MB\n"
          "Copie o .zip, o .manifest.json e o .README.md para a pasta de pacotes do painel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
