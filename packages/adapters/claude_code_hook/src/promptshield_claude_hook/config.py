"""Configuração do hook: arquivo JSON do administrador, com variáveis de ambiente por cima."""
from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATHS = (
    "/etc/promptshield/claude-code-hook.json",
    "/Library/Application Support/PromptShield/claude-code-hook.json",
    "C:\\ProgramData\\PromptShield\\hook.json",  # Windows, nível de máquina (instalação em massa)
)


@dataclass
class Config:
    api_url: str = ""
    api_key: str = ""
    fail_mode: str = "open"               # open: permite e registra localmente | closed: bloqueia
    timeout_seconds: float = 3.0           # tempo para a API responder; menor que o timeout do hook no Claude Code
    integration_status: str = "partial"
    department: str | None = None
    user_id: str | None = None
    device_id: str | None = None
    spool_path: str | None = None
    max_text_chars: int = 200_000
    source_path: str | None = None

    @property
    def usable(self) -> bool:
        return bool(self.api_url and self.api_key)


def user_config_path() -> str:
    return str(Path.home() / ".promptshield" / "hook.json")


def config_path() -> str | None:
    env = os.environ.get("PROMPTSHIELD_HOOK_CONFIG")
    if env:
        return env
    user = user_config_path()
    if Path(user).is_file():  # configuração do usuário (o assistente `setup` grava aqui; funciona no Windows sem variável de ambiente)
        return user
    for p in DEFAULT_PATHS:
        if Path(p).is_file():
            return p
    return None


def _read_key(data: dict) -> str:
    if data.get("api_key"):
        return str(data["api_key"])
    f = data.get("api_key_file")
    if f:
        try:
            return Path(f).read_text(encoding="utf-8-sig").strip()
        except OSError:
            return ""
    return ""


def load(path: str | None = None) -> Config:
    cfg = Config()
    p = path or config_path()
    if p:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        cfg.source_path = p
        cfg.api_url = str(data.get("api_url", "")).rstrip("/")
        cfg.api_key = _read_key(data)
        cfg.fail_mode = data.get("fail_mode", cfg.fail_mode)
        cfg.timeout_seconds = float(data.get("timeout_seconds", cfg.timeout_seconds))
        cfg.integration_status = data.get("integration_status", cfg.integration_status)
        cfg.department = data.get("department")
        cfg.user_id = data.get("user_id")
        cfg.device_id = data.get("device_id")
        cfg.spool_path = data.get("spool_path")
        cfg.max_text_chars = int(data.get("max_text_chars", cfg.max_text_chars))
    env = os.environ
    cfg.api_url = env.get("PROMPTSHIELD_API_URL", cfg.api_url).rstrip("/")
    cfg.api_key = env.get("PROMPTSHIELD_API_KEY", cfg.api_key)
    cfg.fail_mode = env.get("PROMPTSHIELD_FAIL_MODE", cfg.fail_mode)
    if env.get("PROMPTSHIELD_TIMEOUT"):
        cfg.timeout_seconds = float(env["PROMPTSHIELD_TIMEOUT"])
    cfg.department = env.get("PROMPTSHIELD_DEPARTMENT", cfg.department)
    cfg.user_id = env.get("PROMPTSHIELD_USER_ID", cfg.user_id)
    cfg.spool_path = env.get("PROMPTSHIELD_SPOOL_PATH", cfg.spool_path)
    if cfg.fail_mode not in ("open", "closed"):
        cfg.fail_mode = "open"
    return cfg


def default_device_id() -> str:
    return platform.node() or "desconhecido"
