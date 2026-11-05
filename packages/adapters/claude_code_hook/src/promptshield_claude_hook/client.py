"""Cliente HTTP mínimo (urllib). Qualquer falha vira ApiError: o chamador aplica o modo de falha."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import Config


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None, stopped: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.stopped = stopped      # a empresa/licença parou a inspeção de propósito (não é falha de rede): a ferramenta do usuário segue normal


def _request(cfg: Config, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not cfg.usable:
        raise ApiError("configuração incompleta (api_url e api_key)")
    if not cfg.api_url.lower().startswith(("https://", "http://")):  # urlopen também abriria file:// e outros esquemas
        raise ApiError("api_url precisa começar com https:// (ou http:// só em testes locais)")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg.api_url + path, data=data, method=method, headers={  # noqa: S310
        "X-API-Key": cfg.api_key, "Content-Type": "application/json", "User-Agent": "promptshield-claude-hook/0.1"})
    try:
        # URL da configuração do administrador, com esquema http(s) verificado acima
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        retry = exc.headers.get("Retry-After") if exc.headers else None
        try:
            wait = float(retry) if retry else None
        except ValueError:
            wait = None
        hdr = exc.headers
        if hdr and (hdr.get("X-PromptShield-Inspection") == "stopped" or hdr.get("X-PromptShield-Suspended")):
            raise ApiError("inspeção PARADA pela licença ou pelo contrato da empresa; sua ferramenta segue normal, sem inspeção",
                           status=exc.code, stopped=True) from exc
        raise ApiError(f"API respondeu {exc.code}", status=exc.code, retry_after=wait) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:  # inclui timeout e conexão recusada
        raise ApiError(f"API indisponível ({type(exc).__name__})") from exc


def post_event(cfg: Config, event: dict[str, Any]) -> dict[str, Any]:
    return _request(cfg, "POST", "/v1/events", event)


def put_ias(cfg: Config, keys: list[str], mode: str = "add") -> dict[str, Any]:
    """Informa ao servidor quais IAs foram escolhidas nesta máquina (aparece no painel de sensores). `add` acumula entre execuções do assistente."""
    return _request(cfg, "PUT", "/v1/device/ias", {"ias": keys, "mode": mode})


def get_hook_config(cfg: Config) -> dict[str, Any]:
    return _request(cfg, "GET", "/v1/hook-config")
