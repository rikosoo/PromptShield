"""Assistente interativo: vincula as ferramentas do usuário ao PromptShield, quantas vezes quiser.

    python -m promptshield_claude_hook setup

O que cada opção faz de verdade (nada é instalado sem você confirmar):
  1  Claude Code: grava ~/.promptshield/hook.json e acrescenta os hooks ao ~/.claude/settings.json (com cópia de segurança).
  2  GitHub Copilot CLI: grava ~/.copilot/hooks/promptshield.json (arquivo só nosso). EXPERIMENTAL; o Copilot no VS Code não é coberto.
  3  Codex (OpenAI): NÃO disponível. Há hooks no Codex, mas o formato não pôde ser lido na documentação oficial: A VERIFICAR.
  3  ChatGPT e Claude no navegador: guia da extensão (o navegador não permite instalar sozinho).
  5  Abre o console no navegador.   6 Testa a conexão.   7 Remove os vínculos (Claude Code e Copilot).
Status honesto: o hook do Claude Code é PARCIAL; Desktop (aba Code) e VS Code: A VERIFICAR; o chat do app Claude Desktop não é coberto.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import browser, client, config, ias

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse")
MARK = "promptshield_claude_hook"


# ---------- configuração e settings do Claude Code (funções puras, testadas) ----------
def claude_settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")  # A VERIFICAR: nome e semântica na documentação atual
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def copilot_hooks_path() -> Path:
    base = os.environ.get("COPILOT_HOME")  # documentado: $COPILOT_HOME/hooks/
    return (Path(base) if base else Path.home() / ".copilot") / "hooks" / "promptshield.json"


def codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"     # documentado: ~/.codex/hooks.json (CODEX_HOME: A VERIFICAR, por isso não usado)


def codex_command() -> str:
    """Uma linha de comando (o Codex usa `command` como texto, não lista de argumentos)."""
    exe, args = self_command()
    return " ".join([f'"{exe}"'] + [f'"{a}"' for a in args] + ["--codex"])


def merge_codex(data: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta os nossos hooks ao hooks.json do Codex sem tocar nos do usuário; repetir não duplica.
    Formato conferido na documentação de Hooks do Codex (cópia colada pelo dono do produto em 2026-11-04): evento > grupo (matcher) > handlers {type, command, timeout em segundos}."""
    data = remove_ours(data)
    hooks = data.setdefault("hooks", {})
    cmd = codex_command()
    for ev in EVENTS:
        handler = {"type": "command", "command": cmd, "commandWindows": cmd, "timeout": 10, "statusMessage": "PromptShield"}
        group: dict[str, Any] = {"hooks": [handler]}
        if ev != "UserPromptSubmit":
            group = {"matcher": "*", **group}    # no UserPromptSubmit o matcher é ignorado pelo Codex
        hooks.setdefault(ev, []).append(group)
    return data


def copilot_doc() -> dict[str, Any]:
    """Arquivo de hooks do Copilot CLI (versão 1). Eventos em camelCase => payloads camelCase. Usa `bash` e `powershell` (documentados)."""
    exe, args = self_command()
    hooks: dict[str, Any] = {}
    for ev in ("userPromptSubmitted", "preToolUse", "postToolUse"):
        parts = " ".join([f'"{exe}"'] + [a if a.startswith("-") else f'"{a}"' for a in args] + ["--copilot", ev])
        hooks[ev] = [{"type": "command", "bash": parts, "powershell": f"& {parts}", "timeoutSec": 10}]
    return {"version": 1, "hooks": hooks}


def self_command() -> tuple[str, list[str]]:
    """Como o Claude Code e o Copilot devem chamar o hook: do sensor baixado (.pyz), de um executável congelado ou do pacote instalado."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    main = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if main is not None and main.suffix == ".pyz" and main.is_file():
        return sys.executable, [str(main.resolve())]
    return sys.executable, ["-m", MARK]


def our_entry() -> dict[str, Any]:
    exe, args = self_command()
    return {"type": "command", "command": exe, "args": args, "timeout": 10}


def _is_ours(h: Any) -> bool:
    text = json.dumps(h.get("args", [])) + str(h.get("command", "")) if isinstance(h, dict) else ""
    return MARK in text or "promptshield-sensor" in text


def remove_ours(data: dict[str, Any]) -> dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for ev in list(hooks):
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                g = {**g, "hooks": [h for h in g["hooks"] if not _is_ours(h)]}
                if not g["hooks"]:
                    continue
            kept.append(g)
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    if not hooks:
        del data["hooks"]
    return data


def merge_hooks(data: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta os nossos hooks sem tocar nos do usuário; repetir não duplica."""
    data = remove_ours(data)
    hooks = data.setdefault("hooks", {})
    for ev in EVENTS:
        group: dict[str, Any] = {"hooks": [our_entry()]}
        if ev != "UserPromptSubmit":
            group = {"matcher": "*", **group}
        hooks.setdefault(ev, []).append(group)
    return data


def is_installed(data: dict[str, Any]) -> bool:
    hooks = data.get("hooks") or {}
    return all(any(_is_ours(h) for g in hooks.get(ev, []) if isinstance(g, dict) for h in g.get("hooks", [])) for ev in EVENTS)


def read_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("o settings.json não é um objeto JSON")
    return data


def write_settings(path: Path, data: dict[str, Any]) -> Path | None:
    """Grava sem BOM, com cópia de segurança do arquivo anterior. Devolve o caminho da cópia."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.is_file():
        backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d%H%M%S}")
        backup.write_bytes(path.read_bytes())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return backup


def write_hook_config(api_url: str, api_key: str, department: str | None = None, fail_mode: str = "open") -> str:
    path = Path(config.user_config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"api_url": api_url.rstrip("/"), "api_key": api_key, "fail_mode": fail_mode,
                            "timeout_seconds": 3, "integration_status": "partial"}
    if department:
        data["department"] = department
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    try:
        if os.name == "nt":  # só o seu usuário lê a chave
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:(R,W)"],  # noqa: S603, S607
                           capture_output=True, check=False)
        else:
            path.chmod(0o600)
    except OSError:
        pass
    return str(path)


def create_key_with_mock_login(api_url: str, email: str, name: str) -> str:
    """Só com o login de teste (OIDC_MODE=mock): pega um token simulado e cria a chave pela própria API."""
    def call(path: str, body: dict, token: str | None = None) -> dict:
        if not api_url.lower().startswith(("http://", "https://")):
            raise client.ApiError("api_url inválida")
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
        req = urllib.request.Request(api_url.rstrip("/") + path, data=json.dumps(body).encode(), headers=headers, method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            raise client.ApiError(f"API respondeu {exc.code}", status=exc.code) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise client.ApiError(f"API indisponível ({type(exc).__name__})") from exc

    token = call("/dev/token", {"email": email})["access_token"]
    return call("/v1/api-keys", {"name": name}, token)["key"]


# ---------- interface ----------
class Wizard:
    def __init__(self, ask: Callable[[str], str] = input, secret: Callable[[str], str] = getpass.getpass,
                 say: Callable[..., None] = print, open_url: Callable[[str], Any] = webbrowser.open) -> None:
        self.ask, self.secret, self.say, self.open_url = ask, secret, say, open_url
        self.console_url = "http://localhost:3000"

    # -- ajuda
    def status(self) -> None:
        cfg = config.load()
        try:
            installed = is_installed(read_settings(claude_settings_path()))
        except (OSError, ValueError):
            installed = False
        self.say("\nSituação atual")
        self.say(f"  Servidor: {cfg.api_url or '(não configurado)'}   chave: {'definida' if cfg.api_key else 'ausente'}")
        self.say(f"  Claude Code: {'VINCULADO' if installed else 'não vinculado'}   ({claude_settings_path()})")
        self.say(f"  GitHub Copilot CLI: {'VINCULADO' if copilot_hooks_path().is_file() else 'não vinculado'}   ({copilot_hooks_path()})")

    def yes(self, prompt: str) -> bool:
        return self.ask(f"{prompt} [digite 'sim' para continuar] ").strip().lower() in ("sim", "s")

    # -- conexão e chave
    def ensure_config(self) -> bool:
        cfg = config.load()
        if cfg.usable:
            return True
        self.say("\nPrimeiro, o endereço do servidor e a chave de API do seu tenant.")
        url = self.ask("Endereço da API [http://localhost:8000]: ").strip() or "http://localhost:8000"
        self.say("Como obter a chave:\n  1) colar uma chave que já tenho\n  2) abrir o console no navegador para criar (Privacidade e segurança)\n"
                 "  3) criar automaticamente (só funciona com o login de teste, OIDC_MODE=mock)")
        how = self.ask("Escolha [1]: ").strip() or "1"
        key = ""
        if how == "2":
            self.console_url = self.ask(f"Endereço do console [{self.console_url}]: ").strip() or self.console_url
            self.open_url(self.console_url.rstrip("/") + "/privacy")
            self.say("O navegador abriu. Entre, vá em 'Chaves de API', crie uma chave e copie (ela aparece uma vez).")
            key = self.secret("Cole a chave aqui (não aparece ao digitar): ").strip()
        elif how == "3":
            email = self.ask("E-mail do administrador do tenant: ").strip()
            try:
                key = create_key_with_mock_login(url, email, f"setup-{datetime.now():%Y%m%d-%H%M}")
                self.say("Chave criada pela API (modo de teste).")
            except client.ApiError as exc:
                self.say(f"FALHOU: {exc}. Esse modo só existe com o login de teste e precisa do túnel aberto.")
                return False
        else:
            key = self.secret("Cole a chave (não aparece ao digitar): ").strip()
        if not key.startswith("ps_"):
            self.say("A chave deve começar com ps_. Nada foi gravado.")
            return False
        dept = self.ask("Departamento (opcional): ").strip() or None
        self.say(f"Configuração gravada em {write_hook_config(url, key, dept)}")
        return True

    def test(self) -> bool:
        cfg = config.load()
        try:
            remote = client.get_hook_config(cfg)
        except client.ApiError as exc:
            self.say(f"FALHOU: {exc}. O túnel/servidor está de pé? (curl http://localhost:8000/health)")
            return False
        self.say(f"OK. Servidor respondeu; modo de falha no tenant: {remote.get('failure_mode')}")
        return True

    # -- opções
    def claude_code(self) -> None:
        if not self.ensure_config():
            return
        path = claude_settings_path()
        self.say("\nO que será capturado, e SÓ nesta máquina e neste usuário:")
        self.say("  - cada prompt que você digita no Claude Code e cada comando/ação que o agente propõe;")
        self.say("  - os dados vão para o servidor configurado acima; o texto é mascarado pelo servidor;")
        self.say("  - sem captura oculta: você pode remover quando quiser (opção 6).")
        self.say(f"Será alterado: {path} (cópia de segurança antes).")
        self.say("Vale para o Claude Code no terminal. Aba Code do app Desktop e extensão do VS Code usam os mesmos arquivos de configuração,"
                 " mas o disparo dos hooks lá está A VERIFICAR. O chat comum do app Desktop NÃO é coberto.")
        if not self.yes("Vincular o Claude Code?"):
            self.say("Cancelado.")
            return
        try:
            data = merge_hooks(read_settings(path))
        except (OSError, ValueError) as exc:
            self.say(f"Não alterei nada: não consegui ler {path} ({exc}). Corrija o arquivo e tente de novo.")
            return
        backup = write_settings(path, data)
        self.say(f"Pronto. Claude Code vinculado.{f' Cópia: {backup}' if backup else ''}\nFeche e abra de novo as sessões do Claude Code já abertas.")
        self.test()

    def copilot(self) -> None:
        if not self.ensure_config():
            return
        path = copilot_hooks_path()
        self.say("\nGitHub Copilot CLI (EXPERIMENTAL). Será criado um arquivo só nosso, sem mexer em outras configurações:")
        self.say(f"  {path}")
        self.say("  - captura os prompts e as ações de ferramenta do Copilot CLI nesta máquina, enviando ao servidor configurado;")
        self.say("  - o evento de prompt só MONITORA (o Copilot descarta a resposta do hook); bloquear/pedir confirmação vale para ações de ferramenta;")
        self.say("  - NÃO cobre o Copilot dentro do VS Code nem as sugestões em linha (a documentação lida não os lista como superfície de hooks).")
        self.say("  - os nomes das ferramentas do Copilot não constam na página lida: A VERIFICAR; só testado com entradas simuladas.")
        if not self.yes("Vincular o GitHub Copilot CLI?"):
            self.say("Cancelado.")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(copilot_doc(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        self.say(f"Pronto. Copilot CLI vinculado ({path}). Abra uma nova sessão do Copilot CLI.")
        self.test()

    def codex(self) -> None:
        if not self.ensure_config():
            return
        path = codex_hooks_path()
        self.say(f"\nCodex CLI (EXPERIMENTAL): vou acrescentar os hooks do PromptShield em {path} (com cópia de segurança; os seus não são tocados).")
        if not self.yes("Continuar?"):
            self.say("Cancelado.")
            return
        backup = write_settings(path, merge_codex(read_settings(path)))
        self.say("Pronto." + (f" Cópia: {backup}." if backup else ""))
        self.say("IMPORTANTE: o Codex só roda hooks novos depois que você os revisa. Abra o Codex CLI e digite /hooks para confiar nos do PromptShield.")

    def extension(self) -> None:
        here = Path(__file__).resolve()
        built = next((p for p in (here.parents[i] / "apps" / "extension" / "dist" / "dev" for i in range(2, 7)) if p.is_dir()), None)
        self.say("\nChatGPT (chatgpt.com) e Claude (claude.ai) no navegador, por extensão (EXPERIMENTAL, seletores não conferidos nos sites reais):")
        self.say("  1. Na pasta apps/extension: npm ci  e  npm run build:dev   (precisa do Node.js 20 ou mais novo)")
        self.say("  2. Chrome/Edge: chrome://extensions, ligue o Modo do desenvolvedor, 'Carregar sem compactação', escolha apps/extension/dist/dev")
        self.say("  3. Copie o ID da extensão e coloque no servidor: CORS_ALLOWED_ORIGINS=chrome-extension://<ID>")
        self.say("  4. Em 'service worker' da extensão, configure api_url e api_key (docs/teste-windows.md).")
        if built:
            self.say(f"A pasta já construída existe em: {built}")

    def open_console(self) -> None:
        url = self.ask(f"Endereço do console [{self.console_url}]: ").strip() or self.console_url
        self.console_url = url
        self.open_url(url)
        self.say(f"Abrindo {url} no navegador (o túnel precisa estar aberto).")

    def remove(self) -> None:
        path = claude_settings_path()
        try:
            data = read_settings(path)
        except (OSError, ValueError) as exc:
            self.say(f"Não consegui ler {path}: {exc}")
            return
        cop = copilot_hooks_path()
        if not is_installed(data) and not cop.is_file():
            self.say("Nada vinculado.")
            return
        if not self.yes("Remover os hooks do PromptShield (Claude Code e Copilot CLI)?"):
            self.say("Cancelado.")
            return
        backup = None
        if is_installed(data):
            backup = write_settings(path, remove_ours(data))
        if cop.is_file():
            cop.unlink()
        self.say(f"Removido. Cópia do settings.json anterior: {backup}\nA chave continua em {config.user_config_path()}: apague-a e revogue a chave no console ao terminar.")

    def choose(self) -> None:
        """Escolha por números: configura o que é automático, prepara a extensão e mostra o passo a passo de cada IA escolhida."""
        self.say("\n" + ias.render_list())
        nums: list[int] = []
        for _ in range(3):
            nums, errs = ias.parse_selection(self.ask("Números: "))
            if not errs:
                break
            self.say("  " + "; ".join(errs))
            nums = []
        if not nums:
            self.say("Nada selecionado.")
            return
        self.say("\nSelecionado: " + ", ".join(f"{n}) {ias.BY_N[n].name}" for n in nums))
        tools = ias.tools_for(nums)
        if any(t in tools for t in ("claude_code", "github_copilot_cli", "codex_cli", "browser_extension")) and not self.ensure_config():
            return
        try:
            client.put_ias(config.load(), ias.keys_for(nums), "add")
            self.say("  (as IAs escolhidas foram registradas no painel de Sensores do console)")
        except (client.ApiError, OSError, ValueError) as exc:
            self.say(f"  (não consegui registrar as IAs no painel de Sensores: {exc}; o monitoramento em si não depende disso)")
        results: dict[int, str] = {}
        if "claude_code" in tools:
            self.claude_code()
        if "github_copilot_cli" in tools:
            self.copilot()
        if "codex_cli" in tools:
            self.codex()
        ext_ready = False
        if "browser_extension" in tools:
            cfg = config.load()
            try:
                browser.install_extension(cfg.api_url, cfg.api_key, cfg.department, say=self.say, open_browser=False)
                ext_ready = True
            except (client.ApiError, OSError, ValueError) as exc:
                self.say(f"Extensão: não consegui preparar ({exc}). O servidor foi atualizado (docker compose up -d --build)?")
        exe, args = self_command()
        command = " ".join([f'"{exe}"'] + [f'"{a}"' for a in args])
        self.say("\n===== Passo a passo de cada IA escolhida =====")
        for n in nums:
            self.say("\n" + ias.guide(n, command))
            i = ias.BY_N[n]
            results[n] = ("pronto para o último passo (extensão)" if ext_ready else "extensão NÃO preparada") if i.state == ias.EXT else (
                "configurado" if i.state == ias.AUTO else "siga o passo a passo" if i.state == ias.MANUAL else "indisponível hoje")
        self.say("\n===== Resumo =====")
        for n in nums:
            self.say(f"  {n}) {ias.BY_N[n].name}: {results[n]}")

    def run(self) -> int:
        self.say("PromptShield: vincular ferramentas (pode repetir quantas vezes quiser)")
        actions = {"1": self.claude_code, "2": self.copilot, "3": self.codex, "4": self.extension, "5": self.open_console, "6": self.test, "7": self.remove, "8": self.choose}
        while True:
            self.status()
            self.say("\n  1) Claude Code (terminal; Desktop aba Code e VS Code: a verificar)\n  2) GitHub Copilot CLI (experimental)\n"
                     "  3) Codex (OpenAI)  [indisponível: a verificar]\n  4) ChatGPT e Claude no navegador (extensão)\n"
                     "  5) Abrir o console no navegador\n  6) Testar a conexão\n  7) Remover os vínculos (Claude Code e Copilot)\n"
                     "  8) ESCOLHER quais IAs monitorar (por números, com passo a passo)\n  0) Sair")
            try:
                choice = self.ask("Escolha: ").strip()
            except (EOFError, KeyboardInterrupt):
                self.say("")
                return 0
            if choice in ("0", "q", "sair", ""):
                return 0
            fn = actions.get(choice)
            if fn is None:
                self.say("Opção inválida.")
                continue
            try:
                fn()
            except (EOFError, KeyboardInterrupt):
                self.say("\nInterrompido.")


def main() -> int:
    return Wizard().run()


if __name__ == "__main__":
    sys.exit(main())
