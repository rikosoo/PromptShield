"""Validadores determinísticos: dígito verificador, Luhn, entropia."""
from __future__ import annotations

import math
import re
from collections import Counter

_NON_DIGIT = re.compile(r"\D")


def digits(value: str) -> str:
    return _NON_DIGIT.sub("", value)


def cpf_valid(value: str) -> bool:
    d = digits(value)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def cnpj_valid(value: str) -> bool:
    d = digits(value)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    weights = ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    for k in (0, 1):
        s = sum(int(d[i]) * weights[k][i] for i in range(12 + k))
        r = s % 11
        if (0 if r < 2 else 11 - r) != int(d[12 + k]):
            return False
    return True


def luhn_valid(value: str) -> bool:
    d = digits(value)
    if not 13 <= len(d) <= 19:
        return False
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


_CARD_PREFIX = re.compile(r"^(4|5[1-5]|2[2-7]|3[47]|36|38|6011|65|35)")


def card_plausible(value: str) -> bool:
    d = digits(value)
    return luhn_valid(d) and bool(_CARD_PREFIX.match(d)) and len(set(d)) > 1


def entropy(value: str) -> float:
    if not value:
        return 0.0
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in Counter(value).values())


def iban_valid(value: str) -> bool:
    """IBAN: tamanho plausível e dígitos de controle (módulo 97)."""
    v = re.sub(r"\s+", "", value).upper()
    if not 15 <= len(v) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", v):
        return False
    moved = v[4:] + v[:4]
    num = "".join(str(int(c, 36)) for c in moved)
    return int(num) % 97 == 1


def aba_valid(value: str) -> bool:
    """Routing number dos EUA (ABA): soma ponderada 3-7-1 divisível por 10."""
    d = digits(value)
    if len(d) != 9:
        return False
    w = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    return sum(int(c) * k for c, k in zip(d, w, strict=True)) % 10 == 0
