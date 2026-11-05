"""Entradas hostis grandes não podem travar o motor (antes: 200 mil '.', espaços ou URL levavam minutos)."""
import time

import pytest

from promptshield_detection.engine import analyze

N = 60_000
CASES = {"pontos": "1." * (N // 2), "espacos": " " * N, "url": "http://" + "a." * (N // 2), "email": "a." * (N // 2), "dinheiro": "1,1" * (N // 3),
         "pipes": "| " * (N // 2), "python": " " * N + "return"}


@pytest.mark.parametrize("name", CASES)
def test_large_hostile_input_is_linear_enough(name):
    ev = {"event_id": "00000000-0000-4000-8000-000000000001", "occurred_at": "2026-10-14T12:00:00Z",
          "source": {"channel": "agent_hook", "app": "x", "integration_status": "partial"}, "actor": {"user_id": "u"},
          "kind": "tool_call" if name == "pipes" else "prompt", "content": {"text": CASES[name], "tool_name": "Bash", "tool_input": {"command": CASES[name]}},
          "context": {"session_id": "s", "personal_account": False}}
    started = time.perf_counter()
    analyze(ev)
    assert time.perf_counter() - started < 5, name
