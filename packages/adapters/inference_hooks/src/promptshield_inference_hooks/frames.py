"""Converte o corpo de um frame (`prompt` ou `tool_call`) em blocos prontos para virar eventos universais.

Regras da documentação que isto respeita:
- ignora campos e tipos de bloco desconhecidos (nunca rejeita por isso);
- `type` desconhecido no topo: o chamador deve devolver `allow` (`Frame.known == False`);
- no frame `tool_call`, só a ÚLTIMA mensagem importa (o array pode ganhar mensagens anteriores no futuro);
- anexos trazem só texto extraído; sem texto não há o que inspecionar (e a imagem nunca vem).
O texto NÃO é interpretado aqui: este módulo só reorganiza.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

KNOWN_TYPES = ("prompt", "tool_call")
CONFIG_TEST = "config-test"


@dataclass(frozen=True)
class Block:
    kind: str                      # prompt | response | tool_call | tool_result | file_upload (tipos do evento universal)
    role: str
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    fingerprint: str = ""          # hash estável do conteúdo (identifica o bloco entre turnos)
    msg_index: int = 0             # posição da mensagem de origem em `messages`


@dataclass
class Frame:
    type: str
    request_id: str | None
    application: str
    actor_id: str | None
    actor_email: str | None
    session_id: str | None
    model: str | None
    blocks: list[Block] = field(default_factory=list)
    known: bool = True
    is_config_test: bool = False
    skipped_attachments: int = 0   # anexos sem texto (imagens etc.): NÃO inspecionados
    message_count: int = 0


def _fp(role: str, kind: str, name: str | None, payload: Any) -> str:
    raw = json.dumps([role, kind, name, payload], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def _blocks_of(message: dict[str, Any], skipped: list[int], index: int = 0) -> list[Block]:
    role = message.get("role")
    if role not in ("user", "assistant"):  # papéis novos: ignorados (compatibilidade futura)
        return []
    content = message.get("content")
    if isinstance(content, str):  # tolerância: texto simples
        content = [{"type": "text", "text": content}]
    out: list[Block] = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text" and isinstance(b.get("text"), str) and b["text"].strip():
            kind = "prompt" if role == "user" else "response"
            out.append(Block(kind, role, text=b["text"], fingerprint=_fp(role, kind, None, b["text"])))
        elif t == "tool_use":
            name = _str(b.get("tool_name"))
            tool_input = b.get("input") if isinstance(b.get("input"), dict) else {}
            out.append(Block("tool_call", role, tool_name=name, tool_input=tool_input,
                             fingerprint=_fp(role, "tool_call", name, [b.get("id"), tool_input])))
        elif t == "tool_result":
            text = b.get("content")
            if isinstance(text, str) and text.strip():
                name = _str(b.get("tool_name"))
                out.append(Block("tool_result", role, text=text, tool_name=name,
                                 fingerprint=_fp(role, "tool_result", name, [b.get("tool_use_id"), text])))
        elif t == "attachment":
            text = _str(b.get("text"))
            if text and text.strip():
                meta = {"file_name": _str(b.get("file_name")), "media_type": _str(b.get("media_type")), "size_bytes": b.get("size_bytes")}
                out.append(Block("file_upload", role, text=text, tool_input=meta,
                                 fingerprint=_fp(role, "file_upload", meta["file_name"], text)))
            else:
                skipped[0] += 1
        # outros tipos de bloco: ignorados de propósito
    return [replace(b, msg_index=index) for b in out]


def parse_frame(raw: bytes) -> Frame:
    """Levanta ValueError se o corpo não for um JSON objeto."""
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("corpo não é JSON válido") from exc
    if not isinstance(data, dict):
        raise ValueError("corpo não é um objeto JSON")
    ftype = data.get("type") if isinstance(data.get("type"), str) else ""
    actor = data.get("actor") if isinstance(data.get("actor"), dict) else {}
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    app = _str(source.get("application")) or "desconhecido"
    frame = Frame(type=ftype, request_id=_str(data.get("request_id")), application=app, actor_id=_str(actor.get("id")),
                  actor_email=_str(actor.get("email_address")), session_id=_str(data.get("session_id")), model=_str(data.get("model")),
                  known=ftype in KNOWN_TYPES, is_config_test=app == CONFIG_TEST)
    messages = [m for m in (data.get("messages") or []) if isinstance(m, dict)]
    frame.message_count = len(messages)
    if not frame.known or frame.is_config_test:
        return frame
    skipped = [0]
    if ftype == "tool_call":
        # só a última mensagem (a do assistente que acabou de ser produzida); e só chamadas de ferramenta
        if messages:
            frame.blocks = [b for b in _blocks_of(messages[-1], skipped, len(messages) - 1) if b.kind == "tool_call"]
    else:
        for i, m in enumerate(messages):
            frame.blocks.extend(_blocks_of(m, skipped, i))
    frame.skipped_attachments = skipped[0]
    return frame
