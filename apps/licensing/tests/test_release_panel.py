"""Do construtor ao painel: o pacote construído aparece assinado e o download tem exatamente o SHA-256 do manifesto. PostgreSQL real, SINTÉTICO."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from promptshield_licensing.crypto import private_pem
from test_panel import login, panel  # noqa: F401  (a fixture `panel` e o ajudante de entrada vêm do teste do painel)

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("build_package", ROOT / "infra" / "release" / "build_package.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)           # type: ignore[union-attr]


def test_built_package_is_offered_by_the_panel_and_downloads_intact(panel, tmp_path, vendor_key):  # noqa: F811
    res = bp.build("0.4.0", "https://licencas.exemplo.com.br", tmp_path, signing_key=base64.b64encode(private_pem(vendor_key)).decode(), root=ROOT, with_source=False)
    assert login(panel).status_code == 303
    page = panel.get("/painel/downloads").text
    assert "promptshield-onprem-0.4.0.zip" in page and res["sha256"] in page and "assinatura confere" in page and "Ler o LEIA-ME" in page
    got = panel.get("/painel/downloads/promptshield-onprem-0.4.0.zip")
    assert got.status_code == 200 and hashlib.sha256(got.content).hexdigest() == res["sha256"]            # o que o cliente recebe é o que foi assinado
    with zipfile.ZipFile(BytesIO(got.content)) as z:
        assert "promptshield-onprem-0.4.0/instalar.sh" in z.namelist()
    readme = panel.get("/painel/downloads/promptshield-onprem-0.4.0.zip/leia-me")
    assert readme.status_code == 200 and "guia de instalação" in readme.text and "licencas.exemplo.com.br" in readme.text
    man = json.loads((tmp_path / "promptshield-onprem-0.4.0.zip.manifest.json").read_text())
    assert man["sha256"] == res["sha256"] and man["with_source"] is False
