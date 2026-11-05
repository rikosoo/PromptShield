"""Veredito: HTTP 200 e JSON. `deny_reason` até 500 caracteres; `reference_id` até 50 de [A-Za-z0-9._:/-]."""
from __future__ import annotations

import re
from typing import Any

MAX_DENY_REASON = 500
MAX_REFERENCE_ID = 50
_REF = re.compile(r"^[A-Za-z0-9._:/-]+$")


def allow() -> dict[str, Any]:
    return {"action": "allow"}


def deny(reason: str, reference_id: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"action": "deny", "deny_reason": reason[:MAX_DENY_REASON]}
    if reference_id and len(reference_id) <= MAX_REFERENCE_ID and _REF.match(reference_id):
        out["reference_id"] = reference_id  # inválido seria descartado pela Anthropic; nós nem enviamos
    return out
