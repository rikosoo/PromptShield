"""Busca de palavras-chave em um texto. Função pura (sem banco, sem web): fácil de testar.

Dois modos por palavra:
- exata: o termo aparece no texto (ignora maiúsculas e acentos); `whole_word` exige a palavra inteira;
- aproximada (`fuzzy`): além da exata, aceita palavras PARECIDAS, medidas por distância de edição (erro de digitação, letra a mais ou a
  menos, letras trocadas, plural). A tolerância cresce com o tamanho da palavra, para não casar palavras curtas por acaso.
Limite honesto: é semelhança de LETRAS, não de sentido. "carro" não casa com "automóvel"; e palavras curtas e parecidas podem casar sem querer
(ex.: "fenix" e "felix"): por isso o modo aproximado se desliga por palavra.
"""
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
    fuzzy: bool = False


@dataclass(frozen=True)
class Hit:
    rule: Rule
    approximate: bool               # True quando só casou por semelhança (não existe o termo exato no texto)


def tolerance(n: int) -> int:
    """Quantas edições aceitar numa palavra de `n` letras: até 4 letras, nenhuma; 5 a 8, uma; 9 ou mais, duas."""
    return 0 if n <= 4 else 1 if n <= 8 else 2


def distance(a: str, b: str, limit: int) -> int:
    """Distância de Damerau-Levenshtein (inserção, remoção, troca e transposição de letras vizinhas), com corte: devolve `limit + 1` se passar."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s)


def _exact(norm_text: str, norm_term: str, whole_word: bool) -> bool:
    if not whole_word:
        return norm_term in norm_text
    return re.search(rf"(?<!\w){re.escape(norm_term)}(?!\w)", norm_text) is not None


def _close(text_words: list[str], term_words: list[str]) -> bool:
    """Algum trecho de palavras seguidas do texto é parecido, palavra a palavra, com o termo."""
    n = len(term_words)
    for i in range(len(text_words) - n + 1):
        if all(distance(text_words[i + j], term_words[j], tolerance(len(term_words[j]))) <= tolerance(len(term_words[j])) for j in range(n)):
            return True
    return False


def find_hits(text: str, rules: list[Rule]) -> list[Hit]:
    """Regras cujo termo aparece no texto, exato ou (se a regra permite) parecido. Ordem preservada."""
    if not text or not rules:
        return []
    norm = normalize(text)
    words = _words(norm)
    out: list[Hit] = []
    for r in rules:
        t = normalize(r.term).strip()
        if not t:
            continue
        if _exact(norm, t, r.whole_word):
            out.append(Hit(r, False))
        elif r.fuzzy and (tw := _words(t)) and _close(words, tw):
            out.append(Hit(r, True))
    return out


def find(text: str, rules: list[Rule]) -> list[Rule]:
    return [h.rule for h in find_hits(text, rules)]


def effective_score(calculated: int, hits: list[Rule]) -> int:
    """Pontuação final. Sem pontuação escolhida em nenhuma regra que casou, continua a calculada.
    Com várias regras com pontuação, vale a maior."""
    chosen = [r.score for r in hits if r.score is not None]
    return max(chosen) if chosen else calculated
