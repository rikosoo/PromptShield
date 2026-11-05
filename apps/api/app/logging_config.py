"""Logs estruturados (uma linha JSON por evento) e SEM conteúdo de prompt.

Regra: nada que venha do corpo da requisição entra em log. O log de acesso leva só o modelo da rota (não o caminho real, que pode
trazer ids), método, status, duração e o UUID do tenant. Query strings nunca são registradas. Mensagens de exceção só levam o
TIPO do erro (ver inference_hook.py).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_FIELDS = ("request_id", "tenant_id", "route", "method", "status", "duration_ms")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
               "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for f in _FIELDS:
            if hasattr(record, f):
                out[f] = getattr(record, f)
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None  # sem a mensagem nem o traceback com valores
        return json.dumps(out, ensure_ascii=False)


def configure(enabled: bool = True) -> None:
    if not enabled:
        return
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
