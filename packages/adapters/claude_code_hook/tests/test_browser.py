"""Preparação da extensão do navegador. Zip e servidor SIMULADOS."""
import hashlib
import io
import json
import zipfile

import pytest

from promptshield_claude_hook import browser, client


def make_zip(files: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def test_extract_refuses_path_traversal(tmp_path):
    with pytest.raises(client.ApiError):
        browser.extract_safely(make_zip({"../fora.txt": "x"}), tmp_path / "ext")
    assert not (tmp_path / "fora.txt").exists()


def test_install_writes_device_config_and_checks_hash(tmp_path, monkeypatch):
    data = make_zip({"manifest.json": "{}", "background.js": "//"})
    served = {"/sensor/extension.zip": data, "/sensor/extension-manifest.json": json.dumps({"sha256": hashlib.sha256(data).hexdigest()}).encode()}
    monkeypatch.setattr(browser, "_get", lambda url: served["/" + url.split("/", 3)[3]])
    out = []
    dest = browser.install_extension("http://localhost:8000/", "ps_dev", "TI", tmp_path / "ext", say=out.append, open_browser=False)
    cfg = json.loads((dest / browser.CONFIG_NAME).read_text())
    assert cfg["api_url"] == "http://localhost:8000" and cfg["api_key"] == "ps_dev" and cfg["department"] == "TI" and cfg["user_id"]
    assert (dest / "manifest.json").exists() and any("Carregar sem compactação" in o for o in out)
    served["/sensor/extension-manifest.json"] = json.dumps({"sha256": "0" * 64}).encode()
    with pytest.raises(client.ApiError):
        browser.install_extension("http://localhost:8000", "ps_dev", None, tmp_path / "ext2", say=lambda *_: None, open_browser=False)
    assert not (tmp_path / "ext2").exists()
