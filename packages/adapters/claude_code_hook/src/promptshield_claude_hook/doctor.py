"""`doctor`: diagnóstico de ponta a ponta dos hooks (Claude Code, Codex CLI, GitHub Copilot CLI) nesta máquina.

Para cada CLI com hook instalado, pega o comando EXATAMENTE como está gravado, roda nos shells que existem aqui com um prompt
SINTÉTICO ("SIMULADO: ...", com acentos, para pegar problema de codificação) e mostra o código de saída. É o que o CLI esconde
atrás de "Hook failed". O evento de teste vai de verdade para o servidor, rotulado como simulado. Nada de conteúdo real é lido.

    python <sensor.pyz> doctor
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from . import client, config, hooklog, setup

TIMEOUT = 25
SAMPLE = "SIMULADO: teste do doctor do PromptShield, acentuação: ação, coração, è, Í"


def _handlers(data: dict[str, Any], event: str) -> list[dict[str, Any]]:
    """Handlers de um evento, nos dois formatos (evento > grupos > handlers, ou evento > handlers)."""
    out: list[dict[str, Any]] = []
    for item in (data.get("hooks") or {}).get(event, []) or []:
        if isinstance(item, dict) and isinstance(item.get("hooks"), list):
            out += [h for h in item["hooks"] if isinstance(h, dict)]
        elif isinstance(item, dict):
            out.append(item)
    return out


def _run(argv_or_cmd: list[str] | str, shell_label: str, payload: dict[str, Any], *, shell: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv_or_cmd, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True,  # noqa: S603
                           timeout=TIMEOUT, shell=shell)   # noqa: S602 - o comando vem do arquivo de hooks da própria pessoa; é o que o CLI executaria
        return {"shell": shell_label, "code": p.returncode, "out": p.stdout.decode("utf-8", "replace").strip()[:200],
                "err": p.stderr.decode("utf-8", "replace").strip()[:400], "secs": round(time.monotonic() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"shell": shell_label, "code": None, "out": "", "err": f"sem resposta em {TIMEOUT} s", "secs": TIMEOUT}
    except OSError as exc:
        return {"shell": shell_label, "code": None, "out": "", "err": f"não conseguiu executar: {exc}", "secs": 0.0}


def _shell_runs(cmd: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Roda uma linha de comando nos shells desta máquina: no Windows, cmd e PowerShell; no resto, sh."""
    runs: list[dict[str, Any]] = []
    if os.name == "nt":
        runs.append(_run(f'cmd /d /s /c "{cmd}"', "cmd", payload, shell=False))
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            runs.append(_run([ps, "-NoProfile", "-NonInteractive", "-Command", cmd], "PowerShell", payload))
    else:
        runs.append(_run(cmd, "sh", payload, shell=True))
    return runs


def _claude_payload(event: str = "UserPromptSubmit") -> dict[str, Any]:
    return {"hook_event_name": event, "session_id": "doctor-" + uuid.uuid4().hex[:8], "prompt": SAMPLE, "cwd": str(Path.cwd())}


def check_claude() -> tuple[str, list[dict[str, Any]]]:
    path = setup.claude_settings_path()
    data = setup.read_settings(path) if path.is_file() else {}
    ours = [h for h in _handlers(data, "UserPromptSubmit") if setup._is_ours(h)]
    if not ours:
        return f"Claude Code: sem hook do PromptShield em {path}", []
    h = ours[0]
    argv = [str(h.get("command", ""))] + [str(a) for a in h.get("args", [])]
    return f"Claude Code: hook em {path}\n    comando: {' '.join(argv)}", [_run(argv, "direto (sem shell, como o Claude Code)", _claude_payload())]


def check_codex() -> tuple[str, list[dict[str, Any]]]:
    path = setup.codex_hooks_path()
    data = setup.read_settings(path) if path.is_file() else {}
    ours = [h for h in _handlers(data, "UserPromptSubmit") if setup._is_ours({"command": h.get("command", "")})]
    if not ours:
        return f"Codex CLI: sem hook do PromptShield em {path}", []
    cmd = str(ours[0].get("commandWindows") if os.name == "nt" and ours[0].get("commandWindows") else ours[0].get("command", ""))
    return f"Codex CLI: hook em {path}\n    comando: {cmd}", _shell_runs(cmd, _claude_payload())


def check_copilot() -> tuple[str, list[dict[str, Any]]]:
    path = setup.copilot_hooks_path()
    data = setup.read_settings(path) if path.is_file() else {}
    hs = _handlers(data, "userPromptSubmitted")
    if not hs:
        return f"GitHub Copilot CLI: sem hook em {path}", []
    h = hs[0]
    payload = {"sessionId": "doctor-" + uuid.uuid4().hex[:8], "timestamp": int(time.time() * 1000), "cwd": str(Path.cwd()), "prompt": SAMPLE}
    if os.name == "nt" and h.get("powershell"):
        ps = shutil.which("powershell") or shutil.which("pwsh")
        cmd = str(h["powershell"])
        return f"GitHub Copilot CLI: hook em {path}\n    comando: {cmd}", ([_run([ps, "-NoProfile", "-NonInteractive", "-Command", cmd], "PowerShell", payload)] if ps else [])
    cmd = str(h.get("bash", ""))
    return f"GitHub Copilot CLI: hook em {path}\n    comando: {cmd}", (_shell_runs(cmd, payload) if cmd else [])


def _verdict(r: dict[str, Any]) -> tuple[bool, str]:
    if r["code"] == 0:
        return True, "OK (código 0)"
    if r["code"] is None:
        return False, f"FALHOU: {r['err']}"
    return False, f"FALHOU (código {r['code']})"


def main(args: list[str]) -> int:
    cfg = config.load()
    print("PromptShield doctor (usa só texto sintético)\n")
    print(f"Configuração: {cfg.source_path or '(nenhum arquivo)'}")
    print(f"  servidor: {cfg.api_url or '(vazio)'}   chave: {'definida' if cfg.api_key else 'AUSENTE'}   modo de falha: {cfg.fail_mode}")
    bad = 0
    if not cfg.usable:
        print("  PROBLEMA: sem servidor ou sem chave; rode o instalador de novo.")
        bad += 1
    else:
        try:
            client.get_hook_config(cfg)
            print("  servidor: responde e aceita a chave")
        except client.ApiError as exc:
            print(f"  PROBLEMA: o servidor não respondeu direito: {exc}")
            print("  (se o servidor está atrás de um túnel SSH, ele está aberto?)")
            bad += 1
    for check in (check_claude, check_codex, check_copilot):
        try:
            title, runs = check()
        except (OSError, ValueError) as exc:
            print(f"\n{check.__name__}: não consegui ler o arquivo de hooks ({exc})")
            bad += 1
            continue
        print(f"\n{title}")
        for r in runs:
            ok, text = _verdict(r)
            bad += 0 if ok else 1
            print(f"  [{r['shell']}] {text} em {r['secs']} s")
            if not ok or r["err"]:
                for line in (r["err"] or r["out"]).splitlines()[:4]:
                    print(f"      {line}")
        if "sem hook" in title:
            print("    (não instalado nesta máquina: ignorado)")
    log = hooklog.tail(6)
    print(f"\nÚltimos registros de falha dos hooks ({hooklog.log_path()}):")
    print("\n".join("  " + x for x in log) if log else "  (nenhum)")
    print("\nResumo:", "tudo certo. Confira o evento 'SIMULADO' em Todos os prompts no console." if not bad else f"{bad} problema(s). Cole esta saída para quem vai ajudar.")
    return 0 if not bad else 1
