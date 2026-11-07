"""Busca de palavras-chave em um texto. Função pura (sem banco, sem web): fácil de testar."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize(s: str) -> str:
    """Minúsculas e sem acento: «Confidencial» casa com «confidencial» e «CONFIDENCIAL»."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Rule:
    id: str
    term: str
    whole_word: bool = False
    score: int | None = None        # None: vale a pontuação calculada pelo motor


def _hit(norm_text: str, norm_term: str, whole_word: bool) -> bool:
    if not whole_word:
        return norm_term in norm_text
    return re.search(rf"(?<!\w){re.escape(norm_term)}(?!\w)", norm_text) is not None


def find(text: str, rules: list[Rule]) -> list[Rule]:
    """Regras cujo termo aparece no texto (ordem preservada)."""
    if not text or not rules:
        return []
    norm = normalize(text)
    return [r for r in rules if (t := normalize(r.term).strip()) and _hit(norm, t, r.whole_word)]


def effective_score(calculated: int, hits: list[Rule]) -> int:
    """Pontuação final. Sem pontuação escolhida em nenhuma regra que casou, continua a calculada.
    Com várias regras com pontuação, vale a maior."""
    chosen = [r.score for r in hits if r.score is not None]
    return max(chosen) if chosen else calculated
