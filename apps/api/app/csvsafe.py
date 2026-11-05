"""Planilha: célula que começa com = + - @ vira fórmula. Prefixa com apóstrofo (o conteúdo pode vir de terceiros: nome de máquina, usuário, texto)."""
from __future__ import annotations


def csv_safe(value: object) -> str:
    t = "" if value is None else str(value)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t
