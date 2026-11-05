"""Piso de regressão nos conjuntos A a E (todos sintéticos). Serve para não piorar sem perceber; NÃO é medida de qualidade em dados reais.
A, B, C, E e G guiaram ajustes (medida otimista); F guiou indiretamente (os erros dele inspiraram G); D e H nunca foram usados para ajustar (medida mais honesta)."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("holdout", Path(__file__).resolve().parents[1] / "scripts" / "holdout.py")
holdout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(holdout)

FLOOR = {"holdout_a": 0.95, "holdout_b": 0.97, "holdout_c": 0.97, "holdout_d": 0.85, "holdout_e": 0.96, "holdout_f": 0.88, "holdout_g": 0.97, "holdout_h": 0.89}


@pytest.mark.parametrize("name", FLOOR)
def test_exact_match_floor(name):
    rows, _, misses = holdout.run(name)
    exact = 1 - len(misses) / len(rows)
    assert exact >= FLOOR[name], f"{name}: {exact:.1%} abaixo do piso {FLOOR[name]:.0%}"
