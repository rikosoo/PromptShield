"""Limite de pedidos por janela de 1 minuto, COMPARTILHADO entre processos (tabela `lic_rate_hits`), com queda para a memória do processo se o banco falhar.

A chave vai ao banco como SHA-256: nem IP nem e-mail ficam legíveis. Uma escrita por chamada: só para rotas de baixo volume (ativação, renovação, login)."""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time

from sqlalchemy import text

_lock = threading.Lock()
_mem: dict[str, list[float]] = {}
WINDOW_S = 60


def reset() -> None:
    with _lock:
        _mem.clear()


def _memory_count(key: str, now: float) -> int:
    with _lock:
        recent = [t for t in _mem.get(key, []) if now - t < WINDOW_S]
        recent.append(now)
        _mem[key] = recent
        if len(_mem) > 10_000:
            _mem.clear()
        return len(recent)


def count(key: str, now: float | None = None) -> int:
    """Registra um pedido e devolve quantos já houve nesta janela. `now` informado = só memória (gancho de teste, relógio simulado)."""
    if now is not None:
        return _memory_count(key, now)
    from lic_service.db import session_scope

    wall = time.time()
    try:
        with session_scope() as s:
            n = s.execute(text("""INSERT INTO lic_rate_hits (key, win, n) VALUES (:k, :w, 1)
                                  ON CONFLICT (key, win) DO UPDATE SET n = lic_rate_hits.n + 1 RETURNING n"""),
                          {"k": hashlib.sha256(key.encode()).hexdigest(), "w": int(wall // WINDOW_S)}).scalar_one()
            if random.random() < 0.01:  # noqa: S311 - limpeza barata (janelas com mais de 10 minutos); não é criptografia
                s.execute(text("DELETE FROM lic_rate_hits WHERE win < :w"), {"w": int(wall // WINDOW_S) - 10})
        return int(n)
    except Exception:  # noqa: BLE001 - banco indisponível: a memória do processo segura
        logging.getLogger("lic_service").warning("limite compartilhado indisponível; usando o limite por processo")
        return _memory_count(key, time.monotonic())
