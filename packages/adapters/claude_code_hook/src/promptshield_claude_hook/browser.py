"""Prepara a extensão do navegador (ChatGPT e Claude no site) a partir do servidor. EXPERIMENTAL.

O navegador não deixa um programa instalar extensão sozinho: o sensor baixa a extensão para uma pasta, grava nela a configuração DESTA máquina
(`promptshield-config.json`, com a chave própria do dispositivo) e a pessoa faz UMA vez "Carregar sem compactação" em chrome://extensions
ou edge://extensions. Em máquinas gerenciadas, a instalação forçada por política do navegador é o caminho de produção (A VERIFICAR).
Os seletores dos sites nunca foram conferidos nas páginas reais."""
from __future__ import annotations

import getpass
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import client

CONFIG_NAME = "promptshield-config.json"


def default_dir() -> Path:
    return Path.home() / ".promptshield" / "extension"


def _get(url: str) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        raise client.ApiError("api_url inválida")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - esquema http(s) verificado acima
            return r.read()
    except urllib.error.HTTPError as exc:
        raise client.ApiError(f"servidor respondeu {exc.code} para {url.rsplit('/', 1)[-1]}", status=exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise client.ApiError(f"servidor indisponível ({type(exc).__name__})") from exc


def extract_safely(data: bytes, dest: Path) -> list[str]:
    """Extrai o zip recusando caminhos que saiam da pasta de destino."""
    names = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = dest.resolve()
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if root != target and root not in target.parents:
                raise client.ApiError(f"zip recusado: caminho suspeito ({info.filename})")
            names.append(info.filename)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        z.extractall(dest)  # noqa: S202 - os caminhos foram validados acima
    return names


def install_extension(api_url: str, api_key: str, department: str | None, dest: Path | None = None,
                      say: Callable[..., None] = print, open_browser: bool = True) -> Path:
    dest = dest or default_dir()
    base = api_url.rstrip("/")
    data = _get(f"{base}/sensor/extension.zip")
    want = json.loads(_get(f"{base}/sensor/extension-manifest.json"))["sha256"]
    if hashlib.sha256(data).hexdigest() != want:
        raise client.ApiError("o SHA-256 da extensão não confere; nada foi instalado")
    extract_safely(data, dest)
    cfg: dict[str, Any] = {"api_url": base, "api_key": api_key, "user_id": getpass.getuser(), "fail_mode": "open"}
    if department:
        cfg["department"] = department
    (dest / CONFIG_NAME).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    say(f"Extensão pronta em: {dest}")
    say("Falta UM passo no navegador (o Chrome e o Edge não deixam instalar sozinho):")
    say("  1. Abra chrome://extensions (ou edge://extensions) e ligue o 'Modo do desenvolvedor'.")
    say("  2. Clique em 'Carregar sem compactação' e escolha a pasta acima.")
    say("  3. Abra chatgpt.com ou claude.ai: deve aparecer o aviso 'PromptShield: monitoramento ativo'.")
    if open_browser:
        _try_open_extensions_page()
    return dest


def _try_open_extensions_page() -> None:
    """Melhor esforço: abre a página de extensões. Falha em silêncio (os passos acima já foram impressos)."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", "chrome", "chrome://extensions"])  # noqa: S603, S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Google Chrome", "chrome://extensions"])  # noqa: S603, S607
    except OSError:
        pass
