"""Limite de requisições por credencial (balde de fichas, em memória, por processo).

Limitação conhecida: com vários processos da API cada um tem o seu balde (o limite efetivo vira N vezes o configurado).
Um limite compartilhado exigiria Redis, que o projeto só adota se for realmente necessário (CLAUDE.md).
"""
from __future__ import annotations

import math
import threading
import time

_lock = threading.Lock()
_buckets: dict[str, tuple[float, float]] = {}  # chave -> (fichas, instante da última conta)
MAX_KEYS = 20_000


def reset() -> None:
    with _lock:
        _buckets.clear()


def check(key: str, per_minute: int, now: float | None = None) -> int | None:
    """None se pode passar; senão, segundos (inteiros) até haver uma ficha. `per_minute <= 0` desliga o limite."""
    if per_minute <= 0:
        return None
    now = time.monotonic() if now is None else now
    rate = per_minute / 60.0
    with _lock:
        tokens, last = _buckets.get(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - last) * rate)
        if tokens >= 1.0:
            _buckets[key] = (tokens - 1.0, now)
            if len(_buckets) > MAX_KEYS:  # evita crescer sem limite: descarta baldes já cheios
                for k in [k for k, (t, _) in _buckets.items() if t >= per_minute - 1][: MAX_KEYS // 2]:
                    _buckets.pop(k, None)
            return None
        _buckets[key] = (tokens, now)
        return max(1, math.ceil((1.0 - tokens) / rate))
