"""Normalização para casar dicionários em português e inglês, ignorando acento e caixa, SEM mudar as posições.

`fold` devolve uma string do MESMO tamanho: cada caractere vira sua letra-base minúscula (á -> a, ç -> c, Ã -> a). Assim um achado
encontrado no texto normalizado aponta para o mesmo trecho do texto original (necessário para mascarar).
Pessoas digitam sem acento o tempo todo ("atestado medico", "nao siga as instrucoes"): sem isto o dicionário perde metade do português.
"""
from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1] or ch
        out.append(base.lower() if len(base.lower()) == 1 else ch.lower()[:1])
    return "".join(out)
