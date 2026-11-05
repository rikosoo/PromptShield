"""Os documentos da Etapa 9 não podem afirmar o que o código não sustenta: toda rota, variável de ambiente, teste, caminho de arquivo
e valor padrão citado nos documentos precisa existir/bater com o código. Sem banco de dados."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.main import app

ROOT = Path(__file__).resolve().parents[3]
DOCS = ["lgpd.md", "ameacas.md", "operacao.md", "piloto.md", "siem.md", "inference-hooks.md"]
TICKS = re.compile(r"`([^`\n]+)`")


def text(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0].rstrip("."))


@pytest.fixture(scope="module")
def routes() -> set[tuple[str, str]]:
    return {(m.upper(), norm(p)) for p, ops in app.openapi()["paths"].items() for m in ops}


@pytest.mark.parametrize("doc", DOCS)
def test_every_route_cited_in_the_docs_exists(doc, routes):
    missing = []
    for token in TICKS.findall(text(doc)):
        m = re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE) (/[^ ]*)", token.strip())
        if m and m.group(2).startswith("/v1") and (m.group(1), norm(m.group(2))) not in routes:
            missing.append(token)
    assert missing == []


def test_the_operations_env_table_only_lists_real_variables():
    fields = {f.upper() for f in Settings.model_fields}
    extra = {"WORKER_INTERVAL", "OLD_MASTER_KEY", "NEW_MASTER_KEY"}       # lidas fora da classe Settings (worker e CLI)
    rows = re.findall(r"^\| `([A-Z][A-Z0-9_]+)`(?: / `([A-Z][A-Z0-9_]+)`)? \|", text("operacao.md"), flags=re.M)
    names = {n for row in rows for n in row if n}
    assert names >= {"ORIGINAL_TEXT_MASTER_KEY", "RATE_LIMIT_KEY_PER_MINUTE", "METRICS_TOKEN", "WORKER_INTERVAL"}
    assert [n for n in names if n not in fields | extra] == []


@pytest.mark.parametrize("doc", DOCS)
def test_every_test_and_file_cited_in_the_docs_exists(doc):
    names = {n for f in (ROOT / "apps/api/tests").glob("*.py") for n in re.findall(r"^(?:async )?def (test_\w+)", f.read_text(), flags=re.M)}
    names |= {n for f in ROOT.glob("apps/web/tests/**/*.ts") for n in re.findall(r"""test\(["']([^"']+)["']""", f.read_text())}
    names |= {n for f in ROOT.glob("packages/**/tests/*.py") for n in re.findall(r"^def (test_\w+)", f.read_text(), flags=re.M)}
    bad = []
    for token in TICKS.findall(text(doc)):
        t = token.split("::")[-1]
        if re.fullmatch(r"test_\w+", t) and t not in names:
            bad.append(token)
        if re.fullmatch(r"(?:apps|packages|infra|docs|tests)/[\w./-]+\.\w+", token) and not (ROOT / token).exists():
            bad.append(token)
    assert bad == []


def test_documented_defaults_match_the_code():
    from app.models import Tenant

    ops, lgpd, hooks = text("operacao.md"), text("lgpd.md"), text("inference-hooks.md")
    s = Settings()
    assert Tenant.retention_days.default.arg == 90 and Tenant.original_retention_days.default.arg == 30
    assert re.search(r"`retention_days` \(padrão 90, de 7 a 365\)", ops) and re.search(r"`original_retention_days` \(padrão 30, de 1 a 365", ops)
    assert re.search(r"`retention_days` \(padrão 90\)", lgpd) and re.search(r"`original_retention_days` \(padrão 30", lgpd)
    assert re.search(rf"`RATE_LIMIT_KEY_PER_MINUTE` \| {s.rate_limit_key_per_minute} \|", ops)
    assert re.search(rf"`RATE_LIMIT_USER_PER_MINUTE` \| {s.rate_limit_user_per_minute} \|", ops)
    assert re.search(rf"`INFERENCE_HOOK_BUDGET_MS` \| {s.inference_hook_budget_ms} \|", ops)
    assert re.search(rf"`INFERENCE_HOOK_MAX_BODY_BYTES` \| {s.inference_hook_max_body_bytes} \|", ops)
    assert Tenant.omit_text_categories.default.arg(None) == ["saude"] and "padrão: **saúde**" in lgpd
    assert "orçamento interno é 3.000 ms" in hooks and s.inference_hook_budget_ms == 3000


def test_documented_pilot_targets_match_the_report():
    from app.reports import PILOT_TARGETS

    piloto = text("piloto.md")
    assert PILOT_TARGETS == {"coverage_min": 0.80, "false_positive_max": 0.20, "first_alert_max_hours": 24}
    assert "| 80% ou mais |" in piloto and "| 20% ou menos, e só vale com **30 ou mais itens decididos** |" in piloto and "| 24 horas ou menos |" in piloto
    from app.pilot import MIN_REVIEWS

    assert MIN_REVIEWS == 30


def test_docs_never_claim_what_the_project_does_not_have():
    """Frases que seriam falsas hoje: certificação, KMS, Redis, cobertura de resposta do modelo."""
    corpus = " ".join(text(d) for d in DOCS).lower()
    for claim in ("certificado iso", "certificada soc", "somos conformes", "100% seguro", "totalmente conforme", "garante conformidade"):
        assert claim not in corpus, claim
