"""Importa o histórico local do Claude Code (transcrições .jsonl) como eventos do PromptShield. EXPERIMENTAL.

O que é documentado (code.claude.com/docs/en/claude-directory, lido em 2026-10-15): as transcrições ficam em
`~/.claude/projects/<projeto>/<sessão>.jsonl`, sem cifra, e são apagadas depois de `cleanupPeriodDays` (padrão 30).
O que NÃO é documentado: o formato dos registros. Este módulo lê o formato OBSERVADO no Claude Code 2.1.x
(campos type, uuid, timestamp, sessionId, promptId, message.content). A VERIFICAR a cada versão; registro que não
bate com o esperado é contado e ignorado, nunca inventado.

Privacidade: por padrão só simula (não envia nada). Só prompts e chamadas de ferramenta; respostas do modelo e
resultados de ferramenta (conteúdo de arquivos, saída de comandos) só com opt-in explícito.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import client, translate
from .config import Config, default_device_id

APP = "claude_code_import"
_SKIP_PREFIXES = ("<local-command-", "<command-name>", "<command-message>")


def default_root() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")  # A VERIFICAR: nome e semântica na documentação atual
    return (Path(env) if env else Path.home() / ".claude") / "projects"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _user_text(content: Any) -> str | None:
    """Texto digitado pelo usuário; None se for só tool_result ou texto injetado pelo próprio Claude Code."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    text = text.strip()
    if not text or text.startswith(_SKIP_PREFIXES):
        return None
    return text


def _stringify(value: Any, limit: int) -> str:
    if isinstance(value, list):  # tool_result pode vir como lista de blocos de texto
        value = "\n".join(b.get("text", "") for b in value if isinstance(b, dict))
    return translate._stringify(value, limit)


def iter_records(path: Path) -> Iterator[dict[str, Any] | None]:
    """Uma linha por vez; linha ilegível vira None (contada pelo chamador)."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                yield None
                continue
            yield rec if isinstance(rec, dict) else None


def build_events(rec: dict[str, Any], cfg: Config, *, responses: bool = False, tool_results: bool = False) -> list[dict[str, Any]]:
    """Traduz um registro da transcrição em zero ou mais eventos universais."""
    rtype, msg = rec.get("type"), rec.get("message")
    when, session = _parse_ts(rec.get("timestamp")), rec.get("sessionId")
    if rtype not in ("user", "assistant") or not isinstance(msg, dict) or when is None or not session:
        return []
    if rec.get("isMeta"):
        return []
    lim = cfg.max_text_chars
    base = {
        "occurred_at": when.isoformat(),
        "source": {"channel": "agent_hook", "app": APP, "integration_status": "experimental"},
        "actor": {"user_id": cfg.user_id or translate._os_user(), "device_id": cfg.device_id or default_device_id(),
                  **({"department": cfg.department} if cfg.department else {})},
        "context": {"session_id": str(session), "personal_account": False},
    }
    out: list[dict[str, Any]] = []

    def add(hook_name: str, ref: str, kind: str, content: dict[str, Any]) -> None:
        # mesma fórmula do hook ao vivo: se o hook já enviou este prompt ou chamada, a API trata como duplicado
        eid = translate.event_id_for({"session_id": session, "hook_event_name": hook_name, "tool_use_id": ref if kind != "prompt" else None,
                                      "prompt_id": ref if kind == "prompt" else None})
        out.append({**base, "event_id": eid, "kind": kind, "content": content})

    content = msg.get("content")
    if rtype == "user":
        text = _user_text(content)
        if text is not None and rec.get("promptId"):
            add("UserPromptSubmit", str(rec["promptId"]), "prompt", {"text": translate._clip(text, lim)})
        if tool_results and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                    add("PostToolUse", str(b["tool_use_id"]), "tool_result",
                        {"tool_name": None, "text": _stringify(b.get("content", ""), lim)})
    elif isinstance(content, list):
        for i, b in enumerate(content):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("id"):
                ti = b.get("input") if isinstance(b.get("input"), dict) else {}
                add("PreToolUse", str(b["id"]), "tool_call", translate._tool_content(b.get("name"), ti, lim))
            elif responses and b.get("type") == "text" and b.get("text", "").strip() and rec.get("uuid"):
                add("Response", f"{rec['uuid']}:{i}", "response", {"text": translate._clip(b["text"], lim)})
    return out


def collect(root: Path, cfg: Config, *, since: datetime | None, project: str | None, responses: bool,
            tool_results: bool) -> tuple[list[dict[str, Any]], Counter]:
    stats: Counter = Counter()
    events: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*.jsonl")):
        if project and project.lower() not in path.parent.name.lower():
            continue
        stats["arquivos"] += 1
        for rec in iter_records(path):
            if rec is None:
                stats["linhas ilegíveis"] += 1
                continue
            built = build_events(rec, cfg, responses=responses, tool_results=tool_results)
            if not built:
                stats["registros ignorados"] += 1
            for ev in built:
                if since and datetime.fromisoformat(ev["occurred_at"]) < since:
                    stats["antes de --since"] += 1
                    continue
                stats[ev["kind"]] += 1
                events.append(ev)
    return events, stats


def send(events: list[dict[str, Any]], cfg: Config, per_second: float, say=print) -> Counter:
    """Envio sequencial, com ritmo limitado e espera no 429 (Retry-After). Para no primeiro erro que não seja de ritmo."""
    res: Counter = Counter()
    gap = 1.0 / per_second
    for n, ev in enumerate(events, 1):
        for attempt in range(5):
            try:
                r = client.post_event(cfg, ev)
                res["duplicados (já existiam)" if r.get("duplicate") else "enviados"] += 1
                break
            except client.ApiError as exc:
                if exc.status == 429 and attempt < 4:
                    time.sleep(min(exc.retry_after or 5.0, 65.0))
                    continue
                res["falhas"] += 1
                say(f"PAROU no evento {n}/{len(events)}: {exc}")
                return res
        time.sleep(gap)
        if n % 100 == 0:
            say(f"  {n}/{len(events)}")
    return res


def main(argv: list[str], cfg: Config) -> int:
    ap = argparse.ArgumentParser(prog="promptshield-claude-hook import", description=__doc__.split("\n\n")[0])
    ap.add_argument("--path", type=Path, default=None, help="pasta de projetos (padrão: ~/.claude/projects)")
    ap.add_argument("--since", help="só eventos a partir desta data (AAAA-MM-DD)")
    ap.add_argument("--project", help="só pastas de projeto cujo nome contém este texto")
    ap.add_argument("--include-responses", action="store_true", help="também envia respostas do modelo (opt-in)")
    ap.add_argument("--include-tool-results", action="store_true",
                    help="também envia resultados de ferramenta: conteúdo de arquivos e saída de comandos (opt-in; o mais sensível)")
    ap.add_argument("--send", action="store_true", help="envia de verdade; sem isso só mostra o que seria enviado")
    ap.add_argument("--yes", action="store_true", help="não pede confirmação")
    ap.add_argument("--rate", type=float, default=5.0, help="eventos por segundo (padrão 5; o limite da API por usuário é 600/min)")
    ap.add_argument("--preview", type=int, default=0, help="mostra os N primeiros textos (aparecem no seu terminal)")
    args = ap.parse_args(argv)

    root = args.path or default_root()
    if not root.is_dir():
        print(f"pasta não encontrada: {root}")
        return 1
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except ValueError:
            print("--since precisa estar no formato AAAA-MM-DD")
            return 2
    events, stats = collect(root, cfg, since=since, project=args.project, responses=args.include_responses,
                            tool_results=args.include_tool_results)
    print(f"Pasta: {root}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"Total de eventos a enviar: {len(events)}  (usuário: {cfg.user_id or translate._os_user()}, app: {APP}, status: experimental)")
    if events:
        ts = sorted(e["occurred_at"] for e in events)
        print(f"Período: {ts[0][:10]} a {ts[-1][:10]}")
    for ev in events[: args.preview]:
        print("  -", ev["kind"], (ev["content"].get("text") or json.dumps(ev["content"].get("tool_input") or {}, ensure_ascii=False))[:120].replace("\n", " "))
    if not args.send:
        print("\nSIMULAÇÃO: nada foi enviado. Use --send para enviar.")
        return 0
    if not cfg.usable:
        print("configuração incompleta (api_url e api_key); defina PROMPTSHIELD_HOOK_CONFIG")
        return 1
    if not events:
        return 0
    if not args.yes:
        print(f"\nIsto enviará {len(events)} eventos para {cfg.api_url}. Os textos são os SEUS e podem conter dados sensíveis.")
        if input("Digite 'enviar' para continuar: ").strip().lower() != "enviar":
            print("cancelado")
            return 1
    res = send(events, cfg, max(0.1, args.rate))
    print("Resultado:", dict(res))
    return 1 if res.get("falhas") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], Config()))
