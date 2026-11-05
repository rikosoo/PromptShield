"""Registro local de falhas do hook, para descobrir POR QUE um hook não enviou nada (o CLI só mostra "Hook failed").

Guarda só metadados: horário, IA, evento, tipo e mensagem curta do erro, nomes dos campos recebidos. NUNCA o texto do prompt.
Arquivo: ~/.promptshield/hook.log (ou PROMPTSHIELD_HOOK_LOG). Cresce pouco (corta no meio ao passar de 200 KB). Qualquer falha aqui é engolida."""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 200_000


def log_path() -> Path:
    env = os.environ.get("PROMPTSHIELD_HOOK_LOG")
    return Path(env) if env else Path.home() / ".promptshield" / "hook.log"


def record(app: str, event: str, what: str, exc: BaseException | None = None, keys: list[str] | None = None) -> None:
    try:
        row: dict[str, object] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "app": app, "event": event, "what": what[:300]}
        if exc is not None:
            tb = traceback.extract_tb(exc.__traceback__)
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            if tb:
                last = tb[-1]
                row["where"] = f"{Path(last.filename).name}:{last.lineno}"
        if keys is not None:
            row["fields"] = sorted(keys)[:40]
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_file() and p.stat().st_size > MAX_BYTES:
            p.write_bytes(p.read_bytes()[-MAX_BYTES // 2:])
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 - o log nunca pode derrubar o hook
        pass


def tail(n: int = 8) -> list[str]:
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]
