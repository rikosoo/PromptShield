"""Registro local quando a API está fora do ar em fail-open. Guarda só metadados, nunca o conteúdo."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

MAX_BYTES = 5 * 1024 * 1024


def default_path() -> str:
    return str(Path.home() / ".promptshield" / "claude-hook-spool.jsonl")


def record(path: str | None, hook_event: str, event: dict[str, Any] | None, reason: str) -> bool:
    p = Path(path or default_path())
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if p.exists() and p.stat().st_size > MAX_BYTES:
            return False
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hook_event": hook_event, "reason": reason,
                "event_id": (event or {}).get("event_id"), "kind": (event or {}).get("kind"),
                "tool_name": ((event or {}).get("content") or {}).get("tool_name"),
                "text_length": len(((event or {}).get("content") or {}).get("text") or "")}
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False
