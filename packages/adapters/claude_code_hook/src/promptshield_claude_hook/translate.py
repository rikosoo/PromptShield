"""Entrada do hook do Claude Code -> evento universal do PromptShield."""
from __future__ import annotations

import getpass
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Config, default_device_id

SUPPORTED = ("UserPromptSubmit", "PreToolUse", "PostToolUse")
_NS = uuid.UUID("6f1c2f0a-5a53-4f7d-9d0e-0b6c1e1f6a11")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _stringify(value: Any, limit: int) -> str:
    if isinstance(value, str):
        return _clip(value, limit)
    try:
        return _clip(json.dumps(value, ensure_ascii=False, default=str), limit)
    except (TypeError, ValueError):
        return _clip(str(value), limit)


def _tool_content(name: str | None, ti: dict[str, Any], limit: int) -> dict[str, Any]:
    """Ferramentas de shell mandam o comando; de arquivo mandam o caminho e o conteúdo escrito; demais, o JSON."""
    if name in ("Bash", "PowerShell"):  # no Windows sem Git Bash o Claude Code usa a ferramenta PowerShell; o comando é o mesmo campo
        return {"tool_name": name, "tool_input": {"command": _clip(str(ti.get("command", "")), limit)}}
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        body = ti.get("content") or ti.get("new_string") or ti.get("new_source") or ""
        if not body and isinstance(ti.get("edits"), list):
            body = "\n".join(str(e.get("new_string", "")) for e in ti["edits"] if isinstance(e, dict))
        return {"tool_name": name, "text": _clip(str(body), limit),
                "tool_input": {"file_path": str(ti.get("file_path") or ti.get("notebook_path") or "")}}
    if name == "Read":
        return {"tool_name": name, "tool_input": {"file_path": str(ti.get("file_path", ""))}, "text": ""}
    return {"tool_name": name, "text": _stringify(ti, limit)}


def event_id_for(hook_input: dict[str, Any]) -> str:
    """Determinístico quando há tool_use_id ou prompt_id: repetir o mesmo hook não duplica evento na API."""
    ref = hook_input.get("tool_use_id") or hook_input.get("prompt_id")
    if not ref:
        return str(uuid.uuid4())
    return str(uuid.uuid5(_NS, f"{hook_input.get('session_id', '')}:{hook_input.get('hook_event_name')}:{ref}"))


def build_event(hook_input: dict[str, Any], cfg: Config, app: str = "claude_code") -> dict[str, Any] | None:
    name = hook_input.get("hook_event_name")
    if name not in SUPPORTED:
        return None
    lim = cfg.max_text_chars
    if name == "UserPromptSubmit":
        kind, content = "prompt", {"text": _clip(str(hook_input.get("prompt", "")), lim)}
    elif name == "PreToolUse":
        kind = "tool_call"
        content = _tool_content(hook_input.get("tool_name"), hook_input.get("tool_input") or {}, lim)
    else:
        kind = "tool_result"
        content = {"tool_name": hook_input.get("tool_name"), "text": _stringify(hook_input.get("tool_response", ""), lim)}
    actor: dict[str, Any] = {"user_id": cfg.user_id or _os_user(), "device_id": cfg.device_id or default_device_id()}
    if cfg.department:
        actor["department"] = cfg.department
    if hook_input.get("agent_id"):
        actor["agent_id"] = str(hook_input["agent_id"])
    return {
        "event_id": event_id_for(hook_input),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": {"channel": "agent_hook", "app": app, "integration_status": "experimental" if app == "codex_cli" else cfg.integration_status},
        "actor": actor,
        "kind": kind,
        "content": content,
        # o hook não informa se a conta é pessoal (ver docs/claude-code-hooks.md): fica falso
        "context": {"session_id": str(hook_input.get("session_id") or "") or None, "personal_account": False},
    }


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - qualquer falha de leitura do usuário vira "desconhecido"
        return "desconhecido"


# ---------- GitHub Copilot CLI (EXPERIMENTAL) ----------
# Fonte: github/docs, content/copilot/reference/hooks-reference.md, lido em 2026-10-17 (versão do produto desconhecida).
# Eventos em camelCase recebem campos camelCase (sessionId, timestamp em ms, cwd, prompt, toolName, toolArgs como STRING JSON).
# Nomes das ferramentas do Copilot CLI não estão listados na página lida: A VERIFICAR.
COPILOT_EVENTS = ("userPromptSubmitted", "preToolUse", "postToolUse")
_SHELL_TOOLS = {"bash", "powershell", "shell", "terminal", "run_command", "execute"}  # nomes do Copilot CLI: A VERIFICAR


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {"value": val}
        except ValueError:
            return {"command": raw}
    return {}


def build_copilot_event(event_name: str, data: dict[str, Any], cfg: Config) -> dict[str, Any] | None:
    lim = cfg.max_text_chars
    name = {"UserPromptSubmit": "userPromptSubmitted", "PreToolUse": "preToolUse", "PostToolUse": "postToolUse"}.get(event_name, event_name)
    if name not in COPILOT_EVENTS:
        return None
    session = str(data.get("sessionId") or data.get("session_id") or "")
    tool = data.get("toolName") or data.get("tool_name")
    targs = _args(data.get("toolArgs") if "toolArgs" in data else data.get("tool_input"))
    if name == "userPromptSubmitted":
        kind, content = "prompt", {"text": _clip(str(data.get("prompt", "")), lim)}
    elif name == "preToolUse":
        kind = "tool_call"
        canon = "Bash" if str(tool or "").lower() in _SHELL_TOOLS else tool
        content = _tool_content(canon, targs, lim)
    else:
        kind = "tool_result"
        res = data.get("toolResult") or data.get("tool_result") or ""
        text = res.get("textResultForLlm") or res.get("text_result_for_llm") or "" if isinstance(res, dict) else res
        content = {"tool_name": tool, "text": _stringify(text, lim)}
    ts = data.get("timestamp")
    when = datetime.now(timezone.utc)
    if isinstance(ts, (int, float)) and ts > 0:
        when = datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc)
    elif isinstance(ts, str):
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    ref = json.dumps([session, name, ts, tool, targs, data.get("prompt")], sort_keys=True, default=str)
    return {
        "event_id": str(uuid.uuid5(_NS, "copilot:" + ref)),  # determinístico: o mesmo hook repetido não duplica
        "occurred_at": when.isoformat(),
        "source": {"channel": "agent_hook", "app": "github_copilot_cli", "integration_status": "experimental"},
        "actor": {"user_id": cfg.user_id or _os_user(), "device_id": cfg.device_id or default_device_id(),
                  **({"department": cfg.department} if cfg.department else {})},
        "kind": kind, "content": content,
        "context": {"session_id": session or None, "personal_account": False},
    }
