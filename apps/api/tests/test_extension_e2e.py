"""Extensão real (Chromium, build de desenvolvimento) contra a API real com PostgreSQL.

Valida o que a API simulada do Playwright em Node não prova: CORS de verdade, formato real da resposta,
política em modo aplicar e justificativa gravada na auditoria. Pula se o build ou o Chromium não existirem.
"""
from __future__ import annotations

import functools
import http.server
import importlib
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest
import uvicorn

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "apps" / "extension" / "dist" / "dev"
FIXTURES = ROOT / "apps" / "extension" / "tests" / "e2e" / "fixtures"
CHROMIUM = os.environ.get("CHROMIUM_PATH")
PROMPT = "Cliente 529.982.247-25, pode revisar o contrato?"
MASKED = "Cliente ***.***.***-25, pode revisar o contrato?"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def pages_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", _port()), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def set_policy(client, world, name, action, mode="enforce"):
    pol = next(p for p in client.get("/v1/policies", headers=world.user("admin")).json() if p["name"] == name)
    body = {k: pol[k] for k in ("name", "description", "enabled", "scope", "match")} | {"action": action, "mode": mode}
    assert client.put(f"/v1/policies/{pol['id']}", json=body, headers=world.user("admin")).status_code == 200


@pytest.fixture
def stack(client, world, pages_url):
    if not (EXT / "manifest.json").exists():
        pytest.skip("rode `npm run build:dev` em apps/extension")
    if not CHROMIUM:
        pytest.skip("defina CHROMIUM_PATH com um Chromium (ex.: /opt/pw-browsers/chromium)")
    from app import main as app_main
    from app.config import settings

    # a lista de domínios do tenant (na API) só pode RESTRINGIR a da extensão: o domínio de teste precisa estar nela
    r = client.patch("/v1/tenant", json={"monitored_domains": ["127.0.0.1", "chatgpt.com", "claude.ai"]}, headers=world.user("admin"))
    assert r.status_code == 200
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        tempfile.mkdtemp(prefix="ps-ext-"), executable_path=CHROMIUM, headless=False,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    # a API só aceita CORS da origem da própria extensão
    settings.cors_allowed_origins = f"chrome-extension://{ext_id}"
    app = importlib.reload(app_main).app
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    api = f"http://127.0.0.1:{port}"
    sw.evaluate("cfg => chrome.storage.local.set({devConfig: cfg})", {
        "api_url": api, "api_key": world.a["api_key"], "user_id": "rafael.moreira", "department": "Engenharia",
        "domains": ["127.0.0.1"], "fail_mode": "open", "timeout_ms": 5000})
    yield ctx, pages_url
    ctx.close()
    pw.stop()
    server.should_exit = True
    t.join(timeout=5)
    settings.cors_allowed_origins = ""
    importlib.reload(app_main)


def submit(ctx, url, text):
    page = ctx.new_page()
    page.goto(f"{url}/chat.html")
    page.locator("#prompt").click()
    page.keyboard.insert_text(text)
    page.keyboard.press("Enter")
    return page


def sent(page):
    return page.evaluate("window.__sent")


def test_mask_with_real_api(client, world, stack):
    ctx, url = stack
    set_policy(client, world, "Mascarar CPF, CNPJ e contato", "mask")
    page = submit(ctx, url, PROMPT)
    dlg = page.locator("promptshield-ui").locator('[role="dialog"]')
    dlg.wait_for(timeout=20000)
    assert MASKED in dlg.inner_text()
    assert sent(page) == []
    dlg.get_by_role("button", name="Enviar versão mascarada").click()
    page.wait_for_function("window.__sent.length === 1", timeout=10000)
    assert sent(page) == [MASKED]
    [e] = client.get("/v1/events", headers=world.user("leitura")).json()
    assert e["masked_text"] == MASKED and e["decision"] == "mask" and e["channel"] == "browser"
    assert e["app"] == "chatgpt_web" and e["user_id"] == "rafael.moreira" and "pii" in {c["id"] for c in e["categories"]}
    assert "529.982.247" not in str(e)
    assert world.sql("SELECT integration_status FROM events").scalar() == "experimental"


def test_monitor_mode_does_not_interrupt(client, world, stack):
    ctx, url = stack                                    # políticas padrão: todas em modo monitorar
    page = submit(ctx, url, PROMPT)
    page.wait_for_function("window.__sent.length === 1", timeout=20000)
    assert sent(page) == [PROMPT]
    assert page.locator("promptshield-ui").locator('[role="dialog"]').count() == 0
    [e] = client.get("/v1/events", headers=world.user("leitura")).json()
    assert (e["decision"], e["would_decide"]) == ("allow", "mask")


def test_justification_is_audited(client, world, stack):
    ctx, url = stack
    set_policy(client, world, "Mascarar CPF, CNPJ e contato", "ask_justification")
    page = submit(ctx, url, PROMPT)
    dlg = page.locator("promptshield-ui").locator('[role="dialog"]')
    dlg.wait_for(timeout=20000)
    dlg.get_by_label("Justificativa").fill("preciso enviar ao cliente hoje")
    dlg.get_by_role("button", name="Enviar com justificativa").click()
    page.wait_for_function("window.__sent.length === 1", timeout=10000)
    assert sent(page) == [PROMPT]
    log = client.get("/v1/audit-log", headers=world.user("auditor")).json()
    assert any(a["action"] == "event.justification" and a["detail"]["justification"] == "preciso enviar ao cliente hoje" for a in log)


def test_block_with_real_api(client, world, stack):
    ctx, url = stack
    set_policy(client, world, "Mascarar CPF, CNPJ e contato", "block")
    page = submit(ctx, url, PROMPT)
    dlg = page.locator("promptshield-ui").locator('[role="dialog"]')
    dlg.wait_for(timeout=20000)
    assert "Envio bloqueado" in dlg.inner_text()
    assert sent(page) == []


def test_tenant_domain_list_can_only_restrict(client, world, stack):
    """Se o tenant não lista o domínio, a extensão fica inerte depois de buscar a configuração (sem enviar nada à API)."""
    ctx, url = stack
    assert client.patch("/v1/tenant", json={"monitored_domains": ["claude.ai"]}, headers=world.user("admin")).status_code == 200
    sw = ctx.service_workers[0]
    # força a busca da configuração remota, como faz o alarme de 30 minutos
    sw.evaluate("""async () => {
        const c = await chrome.storage.local.get('devConfig');
        const r = await fetch(c.devConfig.api_url + '/v1/extension-config', {headers: {'X-API-Key': c.devConfig.api_key}});
        const j = await r.json();
        await chrome.storage.local.set({remote: {domains: j.domains, policy_url: j.policy_url, failure_mode: j.failure_mode, fetchedAt: Date.now()}});
    }""")
    page = submit(ctx, url, PROMPT)
    page.wait_for_function("window.__sent.length === 1", timeout=20000)    # o site funciona normalmente
    assert page.locator("promptshield-ui").count() == 0                       # sem indicador: domínio fora da lista do tenant
    assert client.get("/v1/events", headers=world.user("leitura")).json() == []


# ---------- build sideload: o que o sensor entrega (ID fixo, configuração do arquivo, CORS padrão) ----------
SIDELOAD = ROOT / "apps" / "extension" / "dist" / "sideload"


def test_sideload_extension_reads_sensor_config_and_reports_to_real_api(client, world, tmp_path):
    import json
    import shutil

    if not CHROMIUM:
        pytest.skip("defina CHROMIUM_PATH")
    if not (SIDELOAD / "manifest.json").exists():
        pytest.skip("rode `node build.mjs --sideload` em apps/extension")
    from app import main as app_main
    from app.config import settings

    ext = tmp_path / "ext"
    shutil.copytree(SIDELOAD, ext)
    port = _port()
    api = f"http://127.0.0.1:{port}"
    # o que o sensor grava ao instalar (chave própria do dispositivo, aqui a chave do tenant de teste)
    (ext / "promptshield-config.json").write_text(json.dumps({"api_url": api, "api_key": world.a["api_key"], "user_id": "rafael.moreira",
                                                              "department": "Pessoal", "fail_mode": "open"}))
    server = uvicorn.Server(uvicorn.Config(app_main.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        tempfile.mkdtemp(prefix="ps-sl-"), executable_path=CHROMIUM, headless=False,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
    try:
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        assert f"chrome-extension://{sw.url.split('/')[2]}" == settings.sideload_extension_origin     # ID fixo = o liberado no CORS da API
        html = (FIXTURES / "chatgpt-like.html").read_text(encoding="utf-8")
        ctx.route("https://chatgpt.com/**", lambda r: r.fulfill(status=200, body=html, content_type="text/html; charset=utf-8"))
        page = ctx.new_page()
        page.goto("https://chatgpt.com/")
        page.wait_for_selector("promptshield-ui", state="attached", timeout=20000)   # o shadow DOM é fechado no build de produção/sideload
        time.sleep(1.5)                                                                # a extensão lê o arquivo de configuração ao subir
        page.locator("#prompt-textarea").click()
        page.keyboard.insert_text(PROMPT)
        page.keyboard.press("Enter")
        page.wait_for_function("window.__sent.length === 1", timeout=20000)
        [e] = client.get("/v1/events", headers=world.user("leitura")).json()
        assert e["app"] == "chatgpt_web" and e["channel"] == "browser" and e["user_id"] == "rafael.moreira" and e["department"] == "Pessoal"
        assert "pii" in {c["id"] for c in e["categories"]} and "529.982.247" not in str(e)
    finally:
        ctx.close()
        pw.stop()
        server.should_exit = True
        t.join(timeout=5)
