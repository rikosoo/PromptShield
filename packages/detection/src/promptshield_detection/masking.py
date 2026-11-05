from __future__ import annotations

from .models import Span


def select_spans(spans: list[Span]) -> list[Span]:
    """Escolhe spans sem sobreposição; o mais longo vence (evita vazar segredo por sobreposição)."""
    chosen: list[Span] = []
    for s in sorted(spans, key=lambda x: (-(x.end - x.start), x.start)):
        if not any(s.start < c.end and s.end > c.start for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda x: x.start)


def apply_masks(text: str, spans: list[Span]) -> str:
    out, pos = [], 0
    for s in select_spans(spans):
        out.append(text[pos:s.start])
        out.append(s.masked)
        pos = s.end
    out.append(text[pos:])
    return "".join(out)
