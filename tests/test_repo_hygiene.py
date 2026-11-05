"""Higiene do repositório: nada de segredo real, .env ou chave privada versionados. Roda no CI sem dependências.

Os testes e fixtures usam segredos SINTÉTICOS de propósito (ver tests/fixtures/synth.py); por isso esses caminhos são ignorados.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_OK = ("tests/", "/tests/", "docs/", "prototipo/", "README", ".md", "scripts/", "examples/")
# exceções explícitas: exemplos SINTÉTICOS embutidos no produto (taxonomia, detector, dados de demonstração)
SYNTHETIC_FILES = {
    "apps/api/app/demo.py": "dados de demonstração sintéticos",
    "packages/detection/src/promptshield_detection/detectors/secrets.py": "chave de exemplo da documentação da AWS (EXAMPLE)",
    "packages/taxonomy/taxonomy.yaml": "exemplos sintéticos positivos e negativos de cada categoria",
}
PATTERNS = {
    "chave privada": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "chave AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "token do GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "token do Slack": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    "chave de API do PromptShield": re.compile(r"\bps_[0-9a-f]{8}_[A-Za-z0-9_-]{30,}\b"),
}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def test_no_env_files_are_tracked():
    bad = [f for f in tracked() if Path(f).name == ".env" or (Path(f).name.startswith(".env.") and Path(f).name != ".env.example")]
    assert bad == [], f"arquivos .env versionados: {bad}"
    assert (ROOT / ".gitignore").read_text().count(".env") >= 1


def test_no_real_looking_secrets_outside_synthetic_fixtures():
    hits = []
    for f in tracked():
        if f in SYNTHETIC_FILES or any(marker in f for marker in SYNTHETIC_OK) or f.endswith((".png", ".ico", ".woff2", ".lock", "package-lock.json")):
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for name, rx in PATTERNS.items():
            if rx.search(text):
                hits.append(f"{f}: {name}")
    assert hits == []


def test_env_example_has_no_filled_secrets():
    text = (ROOT / ".env.example").read_text()
    for line in text.splitlines():
        if re.match(r"^(ORIGINAL_TEXT_MASTER_KEY|OIDC_MOCK_SECRET|OIDC_CLIENT_SECRET|SMTP_PASSWORD|METRICS_TOKEN)=.+", line):
            raise AssertionError(f"valor preenchido em .env.example: {line.split('=')[0]}")
