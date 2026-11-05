"""Carrega packages/taxonomy/taxonomy.yaml (fonte única das 30 categorias)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RISK_WEIGHTS = {"baixo": 15, "medio": 35, "alto": 60, "critico": 80}


@dataclass(frozen=True)
class Category:
    id: str
    nome: str
    grupo: str
    risco_padrao: str
    metodo: str
    exemplos_positivos: tuple[str, ...]
    exemplos_negativos: tuple[str, ...]

    @property
    def weight(self) -> int:
        return RISK_WEIGHTS[self.risco_padrao]


def default_path() -> Path:
    env = os.environ.get("PROMPTSHIELD_TAXONOMY")
    if env:
        return Path(env)
    # layout do monorepo: packages/detection/src/promptshield_detection/ -> packages/taxonomy
    return Path(__file__).resolve().parents[3] / "taxonomy" / "taxonomy.yaml"


@lru_cache(maxsize=4)
def load(path: str | None = None) -> dict[str, Category]:
    data = yaml.safe_load(Path(path or default_path()).read_text(encoding="utf-8"))
    cats = {}
    for c in data["categorias"]:
        cats[c["id"]] = Category(
            id=c["id"], nome=c["nome"], grupo=c["grupo"], risco_padrao=c["risco_padrao"],
            metodo=c["metodo"], exemplos_positivos=tuple(c["exemplos_positivos"]),
            exemplos_negativos=tuple(c["exemplos_negativos"]),
        )
    return cats
