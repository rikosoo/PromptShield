"""Tipos do contrato do motor (ver CLAUDE.md: evento universal e resultado da análise)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KINDS = ("prompt", "response", "tool_call", "tool_result", "file_upload")


@dataclass(frozen=True)
class Finding:
    """Um achado de um detector. `span` é opcional (algumas categorias são do texto inteiro)."""

    category: str
    confidence: float
    rule: str
    span_type: str | None = None
    start: int | None = None
    end: int | None = None
    masked: str | None = None


@dataclass
class Context:
    """Visão normalizada do evento que os detectores recebem."""

    text: str
    kind: str = "prompt"
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    personal_account: bool = False
    allowed_hosts: tuple[str, ...] = ()
    project_names: tuple[str, ...] = ()
    attachments: tuple[dict[str, Any], ...] = ()

    @property
    def folded(self) -> str:
        """Texto em minúsculas e sem acento, do mesmo tamanho do original (ver textnorm.fold)."""
        cached = self.__dict__.get("_folded")
        if cached is None:
            from .textnorm import fold

            cached = self.__dict__["_folded"] = fold(self.text)
        return cached

    @property
    def command(self) -> str | None:
        """Comando shell, quando o evento é uma chamada de ferramenta de shell."""
        if self.kind != "tool_call":
            return None
        if self.tool_input and isinstance(self.tool_input.get("command"), str):
            return self.tool_input["command"]
        return self.text or None


@dataclass
class Span:
    start: int
    end: int
    type: str
    masked: str


@dataclass
class Reason:
    rule: str
    contribution: int
    category: str | None = None


@dataclass
class Analysis:
    categories: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    decision: str = "allow"
    masked_text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)   # só nomes (já mascarados), tamanho e tipo
    score_version: str = ""

    def category_ids(self, min_confidence: float = 0.5) -> set[str]:
        return {c["id"] for c in self.categories if c["confidence"] >= min_confidence}
