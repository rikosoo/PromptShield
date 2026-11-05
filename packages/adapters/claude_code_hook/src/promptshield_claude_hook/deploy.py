"""Instalação silenciosa em NÍVEL DE MÁQUINA, para o TI distribuir por MDM, GPO ou script. EXPERIMENTAL: nunca rodou em MDM real.

    promptshield-claude-hook deploy --api-url https://api.empresa --token pse_... --confirm-employees-notified [--tools claude_code,github_copilot_cli]
    promptshield-claude-hook deploy --uninstall --confirm-employees-notified

Exige administrador (grava em C:\\ProgramData, C:\\Program Files, /etc, /Library). Faz, de forma idempotente e com cópia de segurança:
  1. troca o token de matrícula por uma chave PRÓPRIA desta máquina (POST /v1/enroll) e grava a configuração de máquina;
  2. Claude Code: mescla os hooks no managed-settings.json (documentado em docs/claude-code-hooks.md);
  3. GitHub Copilot CLI: grava um arquivo de hooks de política (policy.d), que o usuário não consegue alterar (fonte: github/docs, hooks-reference.md).
Avisos: a chave da máquina fica legível pelos usuários locais (o hook roda como o usuário); ela só envia eventos e é revogável no console.
O aviso aos empregados é obrigação do cliente: por isso a confirmação é exigida como argumento. Nada de captura oculta (princípio 2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from . import browser, client, config, ias, setup
from .config import Config

CLIENT_VERSION = "0.1"
ALL_TOOLS = ("claude_code", "github_copilot_cli", "codex_cli", "browser_extension")
DEFAULT_TOOLS = ("claude_code", "github_copilot_cli")   # a extensão do navegador exige um clique da pessoa: só entra se pedida (--tools)


def _codex_present() -> bool:
    import shutil
    return shutil.which("codex") is not None or (Path.home() / ".codex").is_dir()


def paths(root: Path | None = None, user: bool = False) -> dict[str, Path]:
    """Caminhos de máquina por sistema operacional. `root` prefixa tudo (testes). `user`: nível do usuário, sem administrador."""
    if user:
        return {"claude": setup.claude_settings_path(), "copilot": setup.copilot_hooks_path(), "codex": setup.codex_hooks_path(), "config": Path(config.user_config_path())}
    sysname = platform.system()
    if sysname == "Windows":
        p = {"claude": Path("C:/Program Files/ClaudeCode/managed-settings.json"),
             "copilot": Path("C:/ProgramData/GitHub/Copilot/policy.d/promptshield.json"),
             "config": Path("C:/ProgramData/PromptShield/hook.json")}
    elif sysname == "Darwin":
        p = {"claude": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
             "copilot": Path("/etc/github-copilot/policy.d/promptshield.json"),
             "config": Path("/Library/Application Support/PromptShield/claude-code-hook.json")}
    else:
        p = {"claude": Path("/etc/claude-code/managed-settings.json"), "copilot": Path("/etc/github-copilot/policy.d/promptshield.json"),
             "config": Path("/etc/promptshield/claude-code-hook.json")}
    if root is not None:
        p = {k: root / str(v).lstrip("/\\").replace(":", "") for k, v in p.items()}
    return p


def machine_hash() -> str | None:
    """SHA-256 de um identificador da máquina, só para a licença não contar duas vezes a mesma máquina reinstalada. Sem o valor bruto."""
    raw = None
    try:
        if sys.platform == "win32":
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                raw = winreg.QueryValueEx(k, "MachineGuid")[0]
        elif sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=5).stdout  # noqa: S603, S607
            m = re.search(r'"IOPlatformUUID" = "([^"]+)"', out)
            raw = m.group(1) if m else None
        else:
            for f in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if Path(f).is_file():
                    raw = Path(f).read_text().strip()
                    break
    except (OSError, ImportError, subprocess.SubprocessError):
        raw = None
    return hashlib.sha256(f"promptshield:{raw}".encode()).hexdigest() if raw else None


def enroll(api_url: str, token: str, tools: list[str], sleep=time.sleep, ias_keys: list[str] | None = None) -> dict[str, Any]:
    if not api_url.lower().startswith(("http://", "https://")):
        raise client.ApiError("api_url precisa começar com https:// (http:// só em testes)")
    body: dict[str, Any] = {"token": token, "hostname": socket.gethostname()[:200], "os": platform.system(), "client_version": CLIENT_VERSION, "tools": tools}
    if ias_keys:
        body["ias"] = ias_keys      # as IAs que a pessoa escolheu: aparecem no painel de sensores do console
    mh = machine_hash()
    if mh:
        body["machine_id_hash"] = mh
    for attempt in range(6):   # matrícula em massa sai por um IP só: no 429 espera o Retry-After e tenta de novo
        req = urllib.request.Request(api_url.rstrip("/") + "/v1/enroll", data=json.dumps(body).encode(), method="POST",  # noqa: S310
                                     headers={"Content-Type": "application/json", "User-Agent": "promptshield-deploy/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 5:
                try:
                    wait = float(exc.headers.get("Retry-After") or 5)
                except (TypeError, ValueError):
                    wait = 5.0
                sleep(min(max(wait, 1.0), 65.0) + random.random())  # noqa: S311 - jitter para espalhar as tentativas, não é criptografia
                continue
            detail = ""
            try:
                detail = json.loads(exc.read().decode()).get("detail", "")
            except (ValueError, OSError, AttributeError):
                pass
            if exc.code == 403 and detail:
                raise client.ApiError(f"matrícula recusada: {detail}", status=403) from exc
            raise client.ApiError(f"matrícula recusada pela API ({exc.code}): token inválido, expirado, revogado ou esgotado", status=exc.code) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise client.ApiError(f"API indisponível ({type(exc).__name__})") from exc
    raise client.ApiError("API ocupada demais (429) depois de várias tentativas")


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        path.chmod(mode)
    except OSError:
        pass


def install(api_url: str, token: str, tools: list[str], department: str | None, fail_mode: str, root: Path | None, force: bool,
            say=print, user: bool = False, ias_keys: list[str] | None = None) -> int:
    p = paths(root, user)
    existing = None
    if p["config"].is_file():
        try:
            existing = json.loads(p["config"].read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            existing = None
    stored_url = str((existing or {}).get("api_url") or "").rstrip("/")
    # Reusa a chave existente só se o servidor é o mesmo; se a pessoa passou outro endereço com um token, matricula de novo
    # (a mesma máquina não ocupa vaga nova: ver docs/licenciamento.md / enrollment).
    reuse = bool(existing and existing.get("api_key")) and not force and (stored_url == api_url.rstrip("/") or not token)
    key = ""
    if reuse:
        say("Esta máquina já está matriculada neste servidor (use --force para matricular de novo).")
        key = existing["api_key"]  # type: ignore[index]
        if ias_keys:    # reinstalar só para informar/atualizar as IAs: usa a chave que já existe, sem gastar token nem vaga
            try:
                client.put_ias(Config(api_url=stored_url or api_url.rstrip("/"), api_key=key, timeout_seconds=10), ias_keys, "set")
                say("IAs informadas ao servidor (painel Sensores): " + ", ".join(ias_keys))
            except client.ApiError as exc:
                if token:
                    say(f"A chave antiga não funcionou ({exc}); matriculando de novo com o token informado.")
                    reuse = False
                else:
                    say(f"Não consegui informar as IAs ao servidor ({exc}). O monitoramento não depende disso.")
    elif existing and existing.get("api_key") and not force and stored_url != api_url.rstrip("/"):
        say(f"O endereço mudou ({stored_url or '?'} -> {api_url.rstrip('/')}): matriculando de novo com o token informado.")
    if not reuse:
        try:
            key = enroll(api_url, token, tools, ias_keys=ias_keys)["api_key"]
        except client.ApiError as exc:
            say(f"FALHOU: {exc}")
            return 1
        cfg: dict[str, Any] = {"api_url": api_url.rstrip("/"), "api_key": key, "fail_mode": fail_mode, "timeout_seconds": 3,
                               "integration_status": "partial"}
        if department:
            cfg["department"] = department
        _write(p["config"], json.dumps(cfg, indent=2) + "\n")
        say(f"Matriculada. Configuração: {p['config']}")
    if "claude_code" in tools:
        data = setup.merge_hooks(setup.read_settings(p["claude"]))
        backup = setup.write_settings(p["claude"], data)
        say(f"Claude Code: hooks em {p['claude']}" + (f" (cópia: {backup})" if backup else ""))
    if "github_copilot_cli" in tools:
        _write(p["copilot"], json.dumps(setup.copilot_doc(), indent=2) + "\n")
        say(f"GitHub Copilot CLI: hooks de política em {p['copilot']}")
    if "codex_cli" in tools:
        if "codex" not in p:
            say("Codex CLI: nível de máquina ainda não suportado (usa requirements.toml gerenciado: A VERIFICAR). Use a instalação por usuário (--user).")
        else:
            data = setup.merge_codex(setup.read_settings(p["codex"]))
            backup = setup.write_settings(p["codex"], data)
            say(f"Codex CLI: hooks em {p['codex']}" + (f" (cópia: {backup})" if backup else ""))
            say("  ATENÇÃO (Codex): hooks novos só rodam depois que VOCÊ os revisa e confia neles. Abra o Codex CLI e digite /hooks para confiar nos hooks do PromptShield.")
    if "browser_extension" in tools:
        try:
            browser.install_extension(api_url, key, department, say=say, open_browser=root is None)
        except (client.ApiError, OSError, ValueError, zipfile.BadZipFile) as exc:
            say(f"AVISO: a extensão do navegador não foi preparada ({exc}). O resto foi instalado.")
    try:
        cfg_obj = Config(api_url=api_url.rstrip("/"), api_key=key, timeout_seconds=5)
        client.get_hook_config(cfg_obj)
        say("Conexão testada: OK.")
    except client.ApiError as exc:
        say(f"AVISO: instalado, mas o teste de conexão falhou ({exc}).")
    return 0


def uninstall(root: Path | None, say=print, user: bool = False) -> int:
    p = paths(root, user)
    if p["claude"].is_file():
        data = setup.read_settings(p["claude"])
        if setup.is_installed(data):
            setup.write_settings(p["claude"], setup.remove_ours(data))
            say(f"Claude Code: hooks removidos de {p['claude']}")
    ext = browser.default_dir()
    if user and ext.is_dir():
        import shutil
        shutil.rmtree(ext)
        say(f"Removida a pasta da extensão: {ext} (remova também a extensão em chrome://extensions)")
    if "codex" in p and p["codex"].is_file():
        data = setup.read_settings(p["codex"])
        setup.write_settings(p["codex"], setup.remove_ours(data))
        say(f"Codex CLI: hooks do PromptShield removidos de {p['codex']}")
    for k in ("copilot", "config"):
        if p[k].is_file():
            p[k].unlink()
            say(f"Removido: {p[k]}")
    say("Revogue o dispositivo no console (a chave desta máquina continua válida até lá).")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="promptshield-claude-hook deploy", description="Instalação silenciosa em nível de máquina (EXPERIMENTAL).")
    ap.add_argument("--api-url")
    ap.add_argument("--token", help="token de matrícula (pse_...) criado no console")
    ap.add_argument("--tools", default=",".join(DEFAULT_TOOLS), help=f"lista separada por vírgula entre: {', '.join(ALL_TOOLS)} (padrão: {', '.join(DEFAULT_TOOLS)})")
    ap.add_argument("--ias", help="números das IAs a monitorar, separados por vírgula (ver --list-ias); substitui --tools")
    ap.add_argument("--list-ias", action="store_true", help="mostra a lista numerada de IAs e sai")
    ap.add_argument("--department")
    ap.add_argument("--fail-mode", choices=("open", "closed"), default="open")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--user", action="store_true", help="instala só para o usuário atual (sem administrador): ~/.claude, ~/.copilot, ~/.promptshield")
    ap.add_argument("--force", action="store_true", help="matricula de novo mesmo que já exista chave nesta máquina")
    ap.add_argument("--root", type=Path, help="prefixo para teste: grava tudo sob esta pasta")
    ap.add_argument("--confirm-employees-notified", action="store_true",
                    help="confirma que os empregados foram avisados sobre o monitoramento (exigido)")
    a = ap.parse_args(argv)
    if a.list_ias:
        print(ias.render_list())
        return 0
    if not a.confirm_employees_notified:
        print("RECUSADO: confirme com --confirm-employees-notified que os empregados foram avisados (obrigação do cliente).")
        return 2
    chosen: list[int] = []
    if a.ias:
        chosen, errs = ias.parse_selection(a.ias)
        if errs:
            print("; ".join(errs))
            return 2
        tools = ias.tools_for(chosen)
    else:
        tools = [t.strip() for t in a.tools.split(",") if t.strip()]
    if a.tools == ",".join(DEFAULT_TOOLS) and not a.ias and a.user and "codex_cli" not in tools and _codex_present():
        tools.append("codex_cli")          # padrão: se o Codex CLI está nesta máquina, entra sozinho (a pessoa ainda precisa confiar nos hooks em /hooks)
    bad = [t for t in tools if t not in ALL_TOOLS]
    if bad:
        print(f"Ferramenta desconhecida: {', '.join(bad)}. Disponíveis: {', '.join(ALL_TOOLS)}.")
        return 2
    if not a.user and os.name != "nt" and a.root is None and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Precisa de administrador (root) para gravar em nível de máquina.")
        return 1
    if a.uninstall:
        return uninstall(a.root, user=a.user)
    if not a.api_url or not a.token:
        print("Informe --api-url e --token.")
        return 2
    code = install(a.api_url, a.token, tools, a.department, a.fail_mode, a.root, a.force, user=a.user, ias_keys=ias.keys_for(chosen) if chosen else None)
    if code == 0 and chosen:
        exe, args = setup.self_command()
        command = " ".join([f'"{exe}"'] + [f'"{x}"' for x in args])
        print("\n===== Passo a passo de cada IA escolhida =====")
        for n in chosen:
            print("\n" + ias.guide(n, command))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
