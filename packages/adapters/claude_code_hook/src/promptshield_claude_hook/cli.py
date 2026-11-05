"""Ponto de entrada: lê o JSON do hook em stdin, consulta a API e responde no formato do Claude Code.

Uso pelo Claude Code:  promptshield-claude-hook            (lê o evento de stdin)
Uso do administrador:  promptshield-claude-hook check      (testa configuração e conexão)
                       promptshield-claude-hook refresh-config   (atualiza o modo de falha a partir da API)
                       promptshield-claude-hook deploy --help    (instalação silenciosa em nível de máquina, para MDM/GPO; EXPERIMENTAL)
                       promptshield-claude-hook setup            (assistente: vincula as ferramentas, menu interativo)
                       promptshield-claude-hook import --help    (importa o histórico local do Claude Code; EXPERIMENTAL)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import client, config, decide, hooklog, spool, translate

MAX_STDIN = 20 * 1024 * 1024
ADMIN = ("check", "refresh-config", "deploy", "setup", "import", "doctor")


def _read_stdin() -> str:
    """UTF-8 sempre (no Windows o padrão é a página de código do console e quebra com certos caracteres)."""
    try:
        return sys.stdin.buffer.read(MAX_STDIN).decode("utf-8", errors="replace").lstrip("\ufeff")
    except (AttributeError, OSError, ValueError):
        return sys.stdin.read(MAX_STDIN)


def _emit(out: dict) -> None:
    """JSON só com ASCII (\\uXXXX): nenhum console, em nenhuma página de código, falha ao escrever."""
    sys.stdout.write(json.dumps(out, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _err(msg: str) -> None:
    try:
        sys.stderr.write(msg + "\n")
    except (UnicodeError, OSError, ValueError):
        pass


def run_hook(raw: str, cfg: config.Config, app: str = "claude_code") -> dict | None:
    """Núcleo testável: devolve o JSON de saída (ou None). Nunca levanta exceção."""
    hook_event = "desconhecido"
    event = None
    try:
        data = json.loads(raw)
        hook_event = str(data.get("hook_event_name", "desconhecido"))
        event = translate.build_event(data, cfg, app)
        if event is None:
            if app == "codex_cli":       # formato do Codex ainda A VERIFICAR: registra quais campos chegaram (sem valores) para ajustarmos
                hooklog.record(app, hook_event, "evento ignorado (nome não suportado ou sem texto do prompt)", keys=list(data) if isinstance(data, dict) else [])
            return None
        result = client.post_event(cfg, event)
        return decide.render(hook_event, result)
    except Exception as exc:  # noqa: BLE001 - qualquer falha cai no modo de falha, nunca derruba o Claude Code
        reason = str(exc) if isinstance(exc, client.ApiError) else f"erro interno ({type(exc).__name__})"
        stopped = isinstance(exc, client.ApiError) and exc.stopped
        mode = "open" if stopped else cfg.fail_mode          # inspeção parada pela licença nunca trava o trabalho da pessoa, mesmo em fail_mode closed
        if mode != "closed" and not stopped:
            spool.record(cfg.spool_path, hook_event, event, reason)
        _err(f"promptshield: {reason}; modo de falha: {mode}")
        hooklog.record(app, hook_event, reason, exc)
        return decide.render_failure(hook_event, mode, reason)


def run_copilot(event_name: str, raw: str, cfg: config.Config) -> dict | None:
    """Mesmo contrato do run_hook, para o GitHub Copilot CLI (EXPERIMENTAL). Nunca levanta exceção."""
    event = None
    try:
        event = translate.build_copilot_event(event_name, json.loads(raw), cfg)
        if event is None:
            return None
        return decide.render_copilot(event_name, client.post_event(cfg, event))
    except Exception as exc:  # noqa: BLE001 - qualquer falha cai no modo de falha, nunca derruba o Copilot
        reason = str(exc) if isinstance(exc, client.ApiError) else f"erro interno ({type(exc).__name__})"
        stopped = isinstance(exc, client.ApiError) and exc.stopped
        mode = "open" if stopped else cfg.fail_mode
        if mode != "closed" and not stopped:
            spool.record(cfg.spool_path, event_name, event, reason)
        _err(f"promptshield: {reason}; modo de falha: {mode}")
        hooklog.record("github_copilot_cli", event_name, reason, exc)
        return decide.render_copilot_failure(event_name, mode, reason)


def cmd_check(cfg: config.Config) -> int:
    print(f"configuração: {cfg.source_path or '(nenhum arquivo; só variáveis de ambiente)'}")
    print(f"api_url: {cfg.api_url or '(vazio)'}  chave: {'definida' if cfg.api_key else 'AUSENTE'}  modo de falha: {cfg.fail_mode}")
    try:
        remote = client.get_hook_config(cfg)
    except client.ApiError as exc:
        print(f"FALHOU: {exc}")
        return 1
    print(f"OK. Modo de falha no tenant: {remote.get('failure_mode')}")
    if remote.get("failure_mode") != cfg.fail_mode:
        print("ATENÇÃO: o modo local difere do tenant. Rode `refresh-config`.")
    return 0


def cmd_refresh(cfg: config.Config) -> int:
    if not cfg.source_path:
        print("sem arquivo de configuração para atualizar")
        return 1
    try:
        mode = client.get_hook_config(cfg)["failure_mode"]
        p = Path(cfg.source_path)
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        data["fail_mode"] = mode
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (client.ApiError, OSError, KeyError, ValueError) as exc:
        print(f"FALHOU: {exc}")
        return 1
    print(f"fail_mode = {mode}")
    return 0


def _hook_main(args: list[str]) -> int:
    cfg = config.load()
    if len(args) >= 2 and args[0] == "--copilot":
        out = run_copilot(args[1], _read_stdin(), cfg)
        if out is not None:
            _emit(out)
        return 0
    app = "codex_cli" if args and args[0] == "--codex" else "claude_code"      # o Codex usa o mesmo esquema de eventos; só o rótulo da IA muda
    out = run_hook(_read_stdin(), cfg, app)
    if out is not None:
        _emit(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ADMIN:
        cfg = config.load()
        if args[0] == "check":
            return cmd_check(cfg)
        if args[0] == "refresh-config":
            return cmd_refresh(cfg)
        if args[0] == "deploy":
            from . import deploy
            return deploy.main(args[1:])
        if args[0] == "setup":
            from . import setup
            return setup.main()
        if args[0] == "doctor":
            from . import doctor
            return doctor.main(args[1:])
        from . import importer
        return importer.main(args[1:], cfg)
    try:
        return _hook_main(args)
    except Exception as exc:  # noqa: BLE001 - um hook NUNCA pode sair com código diferente de 0 por defeito nosso: o CLI mostraria "Hook failed"
        hooklog.record("hook", args[0] if args else "", "falha inesperada antes de enviar", exc)
        _err(f"promptshield: erro interno ({type(exc).__name__}); veja {hooklog.log_path()}")
        return 0
