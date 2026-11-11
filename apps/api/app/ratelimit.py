"""Limite de requisições por credencial (balde de fichas, em memória, por processo).

Dois tipos:
- `check` (balde de fichas, EM MEMÓRIA, por processo): para o tráfego pesado (eventos dos coletores, leitura do console). Com vários processos, cada um
  tem o seu balde (o limite efetivo vira N vezes o configurado).
- `check_shared` (janela fixa de 1 minuto NO BANCO, valendo para todos os processos): só para as rotas sensíveis e de baixo volume (login, matrícula,
  licença), onde N vezes o limite seria um furo. Custa uma escrita por chamada, por isso não é usado nos eventos. Não precisa de Redis (CLAUDE.md).
  A chave vai ao banco como SHA-256: nem e-mail nem IP ficam legíveis. Se o banco falhar, cai para o limite em memória (nunca abre sem limite).
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
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


WINDOW_S = 60


def check_shared(key: str, per_minute: int, now: float | None = None) -> int | None:
    """Como `check`, mas compartilhado entre processos. None se pode passar; senão, segundos até a próxima janela."""
    if per_minute <= 0:
        return None
    from sqlalchemy import text

    from app.db import anonymous_session

    wall = time.time() if now is None else now
    window = int(wall // WINDOW_S)
    digest = hashlib.sha256(key.encode()).hexdigest()
    try:
        with anonymous_session() as s:
            n = s.execute(text("""INSERT INTO rate_hits (key, win, n) VALUES (:k, :w, 1)
                                  ON CONFLICT (key, win) DO UPDATE SET n = rate_hits.n + 1 RETURNING n"""), {"k": digest, "w": window}).scalar_one()
            if random.random() < 0.01:  # noqa: S311 - limpeza barata (janelas com mais de 10 minutos); não é criptografia
                s.execute(text("DELETE FROM rate_hits WHERE win < :w"), {"w": window - 10})
    except Exception:  # noqa: BLE001 - banco indisponível: o limite em memória segura
        logging.getLogger("promptshield").warning("limite compartilhado indisponível; usando o limite por processo", exc_info=False)
        return check(key, per_minute)
    return None if n <= per_minute else max(1, int((window + 1) * WINDOW_S - wall) + 1)
