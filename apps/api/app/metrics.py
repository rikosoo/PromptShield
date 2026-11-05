"""Métricas no formato de texto do Prometheus, em memória. Só rótulos de baixa cardinalidade e SEM dados pessoais:
rota (modelo, nunca o caminho real), método, status e resultado. Nada de tenant, usuário, chave ou conteúdo."""
from __future__ import annotations

import threading
from collections import defaultdict

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_hist: dict[tuple[str, str], list[float]] = {}
_hist_sum: dict[tuple[str, str], float] = defaultdict(float)


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    with _lock:
        _counters[(name, tuple(sorted(labels.items())))] += value


def observe_request(route: str, method: str, seconds: float) -> None:
    key = (route, method)
    with _lock:
        counts = _hist.setdefault(key, [0.0] * (len(BUCKETS) + 1))
        for i, b in enumerate(BUCKETS):
            if seconds <= b:
                counts[i] += 1
        counts[-1] += 1
        _hist_sum[key] += seconds


def reset() -> None:
    with _lock:
        _counters.clear()
        _hist.clear()
        _hist_sum.clear()


def render() -> str:
    lines = ["# HELP ps_http_requests_total Requisições HTTP por rota, método e status", "# TYPE ps_http_requests_total counter"]
    with _lock:
        for (name, labels), v in sorted(_counters.items()):
            lab = ",".join(f'{k}="{val}"' for k, val in labels)
            lines.append(f"{name}{{{lab}}} {v:g}" if lab else f"{name} {v:g}")
        lines += ["# HELP ps_http_request_duration_seconds Duração das requisições", "# TYPE ps_http_request_duration_seconds histogram"]
        for (route, method), counts in sorted(_hist.items()):
            base = f'route="{route}",method="{method}"'
            for b, c in zip(BUCKETS, counts, strict=False):
                lines.append(f'ps_http_request_duration_seconds_bucket{{{base},le="{b:g}"}} {c:g}')
            lines.append(f'ps_http_request_duration_seconds_bucket{{{base},le="+Inf"}} {counts[-1]:g}')
            lines.append(f"ps_http_request_duration_seconds_sum{{{base}}} {_hist_sum[(route, method)]:.6f}")
            lines.append(f"ps_http_request_duration_seconds_count{{{base}}} {counts[-1]:g}")
    return "\n".join(lines) + "\n"
