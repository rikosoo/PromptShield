"""Painel web do fornecedor contra PostgreSQL real: entrada, CSRF, escape de HTML, prazos, código de ativação, alertas, pacotes e auditoria. SINTÉTICO."""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from promptshield_licensing import Installation, sha256_file, sign_package
from sqlalchemy import select, text
from test_service import T0, activate

from lic_service import panel_auth as pa
from lic_service import service
from lic_service.config import settings
from lic_service.db import session_scope
from lic_service.main import app
from lic_service.models import ActivationCode, Admin, AuditEntry, Contract

pytestmark = pytest.mark.db
PW = "Teste-PS-2026!Longa"
EMAIL = "henrique@vendor.example"
H = {"Origin": "http://testserver"}


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "panel_enabled", True)
    monkeypatch.setattr(settings, "panel_secret", "p" * 40)
    monkeypatch.setattr(settings, "panel_cookie_secure", False)          # o teste fala http
    monkeypatch.setattr(settings, "panel_require_totp", True)
    monkeypatch.setattr(settings, "packages_dir", str(tmp_path))
    pa.reset_limits()
    secret = pa.new_totp_secret()
    with session_scope() as s:
        s.add(Admin(email=EMAIL, password_hash=pa.hash_password(PW), totp_secret_enc=pa.encrypt_secret(secret)))
    c = TestClient(app, follow_redirects=False)
    c.totp_secret = secret                                              # type: ignore[attr-defined]
    return c


def code_now(c, offset=0):
    return pa.totp_code(c.totp_secret, int(time.time() // 30) + offset)


def fresh_code():
    with session_scope() as s:
        s.execute(text("UPDATE lic_admins SET last_totp_step = NULL"))


def login(c, password=PW, code=None, email=EMAIL):
    fresh_code()
    return c.post("/painel/entrar", data={"email": email, "password": password, "code": code if code is not None else code_now(c)}, headers=H)


def csrf_of(c):
    html = c.get("/painel/visao-geral").text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def post(c, path, data=None, token=None, headers=H):
    return c.post(path, data={"csrf": token or csrf_of(c), **(data or {})}, headers=headers)


def new_contract(c, name="Acme Ltda"):
    r = post(c, "/painel/clientes", {"customer": name, "devices": "50", "months": "12", "tolerance_days": "15", "on_end": "stop_inspection"})
    assert r.status_code == 303, r.text
    return r.headers["location"].rsplit("/", 1)[-1]


# ---------------------------------------------------------------- acesso
def test_panel_does_not_exist_unless_enabled(monkeypatch):
    monkeypatch.setattr(settings, "panel_enabled", False)
    c = TestClient(app, follow_redirects=False)
    for path in ("/painel/entrar", "/painel/visao-geral", "/painel/downloads", "/painel"):
        assert c.get(path).status_code == 404, path
    assert c.post("/painel/entrar", data={"email": "a", "password": "b"}).status_code == 404
    assert c.get("/health").status_code == 200 and c.get("/v1/public-key").status_code in (200, 503)      # a API pública segue como era


def test_settings_refuse_a_weak_panel_secret():
    import os
    import subprocess
    import sys
    for env, ok in (({"PANEL_ENABLED": "true"}, False), ({"PANEL_ENABLED": "true", "PANEL_SECRET": "curto"}, False), ({"PANEL_ENABLED": "true", "PANEL_SECRET": "x" * 32}, True), ({}, True)):
        r = subprocess.run([sys.executable, "-c", "import lic_service.config"], env={**os.environ, **env}, capture_output=True)
        assert (r.returncode == 0) == ok, env


def test_every_page_needs_a_session(panel):
    for path in ("/painel/visao-geral", "/painel/clientes/novo", "/painel/downloads", "/painel/auditoria", "/painel/senha", f"/painel/contratos/{uuid.uuid4()}"):
        r = panel.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/painel/entrar", path
    for path in ("/painel/clientes", "/painel/sair", "/painel/senha", f"/painel/contratos/{uuid.uuid4()}/encerrar"):
        assert panel.post(path, data={"csrf": "x"}, headers=H).status_code == 303, path


def test_login_needs_password_and_a_fresh_six_digit_code_and_failures_look_the_same(panel):
    ok = login(panel)
    assert ok.status_code == 303 and ok.headers["location"] == "/painel/visao-geral"
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/painel" in cookie
    assert panel.get("/painel/visao-geral").status_code == 200
    bad = [login(panel, password="Errada-12345!x"), login(panel, code="000000"), login(panel, email="ninguem@vendor.example"), login(panel, code="")]
    assert {r.status_code for r in bad} == {401}
    assert len({re.search(r'role="alert"[^>]*>([^<]+)', r.text).group(1) for r in bad}) == 1          # mesma mensagem: não revela o que errou
    # o mesmo código não vale duas vezes
    fresh_code()
    code = code_now(panel)
    assert panel.post("/painel/entrar", data={"email": EMAIL, "password": PW, "code": code}, headers=H).status_code == 303
    assert panel.post("/painel/entrar", data={"email": EMAIL, "password": PW, "code": code}, headers=H).status_code == 401


def test_lockout_after_repeated_failures_even_with_the_right_credentials(panel):
    for _ in range(settings.login_max_failures):
        assert login(panel, password="Errada-12345!x").status_code == 401
    assert login(panel).status_code == 401                                   # certo, mas bloqueado
    with session_scope() as s:
        s.execute(text("UPDATE lic_admins SET locked_until = now() - interval '1 minute'"))
    assert login(panel).status_code == 303


def test_account_without_a_six_digit_secret_cannot_enter_when_the_code_is_required(panel):
    with session_scope() as s:
        s.execute(text("UPDATE lic_admins SET totp_secret_enc = NULL"))
    assert login(panel).status_code == 401
    settings.panel_require_totp = False
    assert login(panel, code="").status_code == 303                          # só em desenvolvimento


# ---------------------------------------------------------------- CSRF, origem, escape, cabeçalhos
def test_csrf_and_origin_are_enforced_on_every_change(panel):
    login(panel)
    token = csrf_of(panel)
    cid = new_contract(panel)
    for path, data in (("/painel/clientes", {"customer": "X"}), (f"/painel/contratos/{cid}/codigo", {"valid_days": "7"}), (f"/painel/contratos/{cid}/encerrar", {"reason": "teste", "confirm": "sim"}),
                       (f"/painel/contratos/{cid}/condicoes", {}), ("/painel/sair", {})):
        assert panel.post(path, data=data, headers=H).status_code == 403, path                                   # sem token
        assert panel.post(path, data={**data, "csrf": "errado"}, headers=H).status_code == 403, path             # token errado
        assert panel.post(path, data={**data, "csrf": token}, headers={"Origin": "http://evil.example"}).status_code == 403, path     # outra origem
    with session_scope() as s:
        assert s.get(Contract, uuid.UUID(cid)).status == "pendente"                                                # nada mudou


def test_html_is_escaped_and_pages_are_not_cacheable_or_frameable(panel):
    login(panel)
    cid = new_contract(panel, name="<script>alert(1)</script> & Cia")
    for path, shows_name in (("/painel/visao-geral", True), (f"/painel/contratos/{cid}", True), ("/painel/auditoria", True)):
        r = panel.get(path)
        assert "<script>alert(1)</script>" not in r.text and "<script" not in r.text.lower(), path          # nunca o HTML cru
        if shows_name:
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text, path                                    # o texto aparece, escapado
        csp = r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src" not in csp and "unsafe-eval" not in csp


# ---------------------------------------------------------------- prazos, código, condições, ações
def activate_contract(cid, vendor_key):
    with session_scope() as s:
        code = service.issue_code(s, s.get(Contract, uuid.UUID(cid)), T0)
    inst = Installation.create()
    activate(vendor_key, inst, code)
    return inst


def test_editing_remaining_days_from_the_panel_is_applied_and_audited_with_the_admin_email(panel, vendor_key):
    login(panel)
    cid = new_contract(panel)
    page = panel.get(f"/painel/contratos/{cid}").text
    assert "começa na <strong>ativação</strong>" in page and 'name="months"' in page                          # antes da ativação: duração em meses
    assert post(panel, f"/painel/contratos/{cid}/prazo", {"action": "months", "months": "24"}).status_code == 303
    activate_contract(cid, vendor_key)
    with session_scope() as s:
        s.execute(text("UPDATE lic_contracts SET starts_at = now(), ends_at = now() + interval '100 days'"))
    page = panel.get(f"/painel/contratos/{cid}").text
    assert re.search(r'data-testid="days-left">(99|100)<', page)
    r = post(panel, f"/painel/contratos/{cid}/prazo", {"action": "add", "days": "30", "reason": "cortesia pela migração"})
    assert r.status_code == 303
    assert re.search(r'data-testid="days-left">(129|130)<', panel.get(f"/painel/contratos/{cid}").text)
    post(panel, f"/painel/contratos/{cid}/prazo", {"action": "set", "end": (service.utcnow() + timedelta(days=45)).date().isoformat(), "reason": "contrato renegociado"})
    assert 44 <= int(re.search(r'data-testid="days-left">(-?\d+)<', panel.get(f"/painel/contratos/{cid}").text).group(1)) <= 46      # o fim é o último segundo do dia, em Brasília
    # sem motivo ou data inválida: aviso de erro e nada muda
    for bad in ({"action": "add", "days": "5", "reason": " "}, {"action": "set", "end": "ontem", "reason": "motivo"}, {"action": "add", "days": "0", "reason": "motivo"}, {"action": "foo"}):
        assert post(panel, f"/painel/contratos/{cid}/prazo", bad).status_code == 303
    after = panel.get(f"/painel/contratos/{cid}").text
    assert 44 <= int(re.search(r'data-testid="days-left">(-?\d+)<', after).group(1)) <= 46 and 'role="alert"' in after
    with session_scope() as s:
        acts = [(e.actor, e.action) for e in s.execute(select(AuditEntry).where(AuditEntry.action.in_(["contract.set_end", "contract.term"])).order_by(AuditEntry.id)).scalars()]
    assert acts == [(EMAIL, "contract.term"), (EMAIL, "contract.set_end"), (EMAIL, "contract.set_end")]


def test_activation_code_is_shown_once_stored_only_as_hash_and_a_new_one_cancels_the_old(panel):
    login(panel)
    cid = new_contract(panel)
    r = post(panel, f"/painel/contratos/{cid}/codigo", {"valid_days": "7"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    first = re.search(r'data-testid="new-code">(psa_[^<]+)<', r.text).group(1)
    assert first not in panel.get(f"/painel/contratos/{cid}").text                                         # recarregar não mostra de novo
    with session_scope() as s:
        assert first not in str(s.execute(text("SELECT * FROM lic_activation_codes")).all()) and first not in str(s.execute(text("SELECT * FROM lic_audit")).all())
    second = re.search(r'data-testid="new-code">(psa_[^<]+)<', post(panel, f"/painel/contratos/{cid}/codigo", {"valid_days": "7"}).text).group(1)
    assert second != first
    with session_scope() as s:
        live = [c for c in s.execute(select(ActivationCode)).scalars() if c.expires_at > service.utcnow()]
        assert len(live) == 1 and live[0].code_hash == service.hash_code(second)
    refused = post(panel, f"/painel/contratos/{cid}/codigo", {"valid_days": "99"})                      # validade fora de 1 a 30: recusa, sem código novo
    assert refused.status_code == 303 and "psa_" not in refused.text


def test_terms_form_applies_validates_and_the_weekly_preset_restores_the_policy(panel):
    login(panel)
    cid = new_contract(panel)
    form = {"devices": "20", "tolerance_days": "30", "on_end": "keep_inspection", "renew_days": "7", "validity_days": "28", "warn_days": "10", "suspend_days": "21", "note": "negociado"}
    assert post(panel, f"/painel/contratos/{cid}/condicoes", form).status_code == 303
    with session_scope() as s:
        k = s.get(Contract, uuid.UUID(cid))
        assert (k.max_devices, k.tolerance_days, k.on_end, k.note) == (20, 30, "keep_inspection", "negociado")
    for bad in ({"validity_days": "10"}, {"warn_days": "30"}, {"renew_days": "0"}, {"suspend_days": "abc"}, {"devices": "-1"}):
        post(panel, f"/painel/contratos/{cid}/condicoes", {**form, **bad})
    with session_scope() as s:
        assert s.get(Contract, uuid.UUID(cid)).max_devices == 20 and s.get(Contract, uuid.UUID(cid)).auth_validity_days == 28        # nenhuma alteração inválida foi gravada
    post(panel, f"/painel/contratos/{cid}/condicoes", {**form, "warn_days": "", "suspend_days": "", "validity_days": "7", "renew_days": "1"})
    with session_scope() as s:
        k = s.get(Contract, uuid.UUID(cid))
        assert k.warn_after_days is None and k.suspend_after_days is None
    post(panel, f"/painel/contratos/{cid}/condicoes", {**form, "preset": "weekly"})
    with session_scope() as s:
        k = s.get(Contract, uuid.UUID(cid))
        assert (k.renew_after_hours, k.auth_validity_days, k.warn_after_days, k.suspend_after_days) == (168, 28, 10, 21)


def test_dangerous_actions_need_the_confirmation_and_reopen_unbind_work(panel, vendor_key):
    login(panel)
    cid = new_contract(panel)
    activate_contract(cid, vendor_key)
    post(panel, f"/painel/contratos/{cid}/encerrar", {"reason": "cancelado a pedido"})                          # sem a caixa de confirmação
    with session_scope() as s:
        assert s.get(Contract, uuid.UUID(cid)).status == "ativo"
    post(panel, f"/painel/contratos/{cid}/encerrar", {"reason": "cancelado a pedido", "confirm": "sim"})
    with session_scope() as s:
        k = s.get(Contract, uuid.UUID(cid))
        assert k.status == "encerrado" and k.close_reason == "cancelado a pedido"
    assert "ENCERRADO" in panel.get("/painel/visao-geral").text
    post(panel, f"/painel/contratos/{cid}/reabrir")
    post(panel, f"/painel/contratos/{cid}/desvincular", {})
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM lic_installations WHERE unbound_at IS NULL")).scalar() == 1      # sem confirmação, nada
    post(panel, f"/painel/contratos/{cid}/desvincular", {"confirm": "sim"})
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM lic_installations WHERE unbound_at IS NULL")).scalar() == 0
        actors = {e.actor for e in s.execute(select(AuditEntry).where(AuditEntry.action.in_(["contract.close", "contract.reopen", "installation.unbind"]))).scalars()}
    assert actors == {EMAIL}


def test_dashboard_shows_internal_alert_then_client_warned_then_suspended(panel, vendor_key):
    login(panel)
    cid = new_contract(panel)
    activate_contract(cid, vendor_key)
    with session_scope() as s:                                       # a ativação do teste usa uma data fixa antiga: traz a última validação para agora
        s.execute(text("UPDATE lic_authorizations SET issued_at = now()"))
        s.execute(text("UPDATE lic_installations SET last_seen_at = now()"))
    page = lambda: panel.get("/painel/visao-geral").text    # noqa: E731
    assert "em dia" in page() and "Só você vê" not in page()
    with session_scope() as s:
        s.execute(text("UPDATE lic_authorizations SET issued_at = now() - interval '8 days 2 hours'"))
    assert "Só você vê este alerta" in page()
    with session_scope() as s:
        s.execute(text("UPDATE lic_authorizations SET issued_at = now() - interval '18 days'"))
    assert "O CLIENTE JÁ ESTÁ SENDO AVISADO" in page()
    with session_scope() as s:
        s.execute(text("UPDATE lic_authorizations SET issued_at = now() - interval '30 days'"))
    assert "INSPEÇÃO SUSPENSA NO CLIENTE" in page() and "<b>1</b>" in page()


def test_change_password_policy_and_old_sessions_die(panel):
    login(panel)
    old = panel.cookies.get("lic_session")
    for new, again in (("curta", "curta"), (PW, PW), ("Outra-Senha-Forte-2026!", "diferente")):
        post(panel, "/painel/senha", {"current": PW, "new": new, "again": again})
    assert login(panel).status_code == 303                                                  # a senha antiga segue valendo: nada foi trocado
    old = panel.cookies.get("lic_session")
    assert post(panel, "/painel/senha", {"current": "errada", "new": "Outra-Senha-Forte-2026!", "again": "Outra-Senha-Forte-2026!"}).status_code == 303
    assert login(panel).status_code == 303
    r = post(panel, "/painel/senha", {"current": PW, "new": "Outra-Senha-Forte-2026!", "again": "Outra-Senha-Forte-2026!"})
    assert r.status_code == 303 and panel.get("/painel/visao-geral").status_code == 200       # a sessão que trocou continua
    other = TestClient(app, follow_redirects=False)
    other.cookies.set("lic_session", old, path="/painel")
    assert other.get("/painel/visao-geral").status_code == 303                                # a sessão anterior caiu
    assert login(panel, password=PW).status_code == 401 and login(panel, password="Outra-Senha-Forte-2026!").status_code == 303


# ---------------------------------------------------------------- pacotes
def make_package(d, vendor_key, version="0.4.0", tamper=False, bad_signature=False):
    name = f"promptshield-onprem-{version}.zip"
    (d / name).write_bytes(b"zip sintetico " + version.encode())
    digest = sha256_file(d / name)
    sig = sign_package(vendor_key, version, digest)
    if bad_signature:
        sig = sign_package(vendor_key, "9.9.9", digest)
    (d / f"{name}.manifest.json").write_text(json.dumps({"version": version, "sha256": digest, "signature": sig, "built_at": "2026-11-11T10:00:00Z"}))
    (d / f"promptshield-onprem-{version}.README.md").write_text("# LEIA-ME\n1. Instale o Docker <b>agora</b>\n")
    if tamper:
        (d / name).write_bytes(b"conteudo trocado depois de assinado")
    return name, digest


def test_packages_are_listed_verified_downloaded_and_audited(panel, tmp_path, vendor_key):
    login(panel)
    assert "Nenhum pacote encontrado" in panel.get("/painel/downloads").text
    name, digest = make_package(tmp_path, vendor_key)
    page = panel.get("/painel/downloads").text
    assert name in page and digest in page and "assinatura confere" in page
    r = panel.get(f"/painel/downloads/{name}")
    assert r.status_code == 200 and r.content == b"zip sintetico 0.4.0" and r.headers["content-type"] == "application/zip"
    readme = panel.get(f"/painel/downloads/{name}/leia-me")
    assert readme.status_code == 200 and "Instale o Docker &lt;b&gt;agora&lt;/b&gt;" in readme.text                  # texto do LEIA-ME é escapado
    with session_scope() as s:
        e = s.execute(select(AuditEntry).where(AuditEntry.action == "package.download")).scalar_one()
        actor, detail = e.actor, e.detail
    assert actor == EMAIL and detail["file"] == name and detail["sha256"] == digest


def test_tampered_or_badly_signed_packages_are_never_delivered(panel, tmp_path, vendor_key):
    login(panel)
    tampered, _ = make_package(tmp_path, vendor_key, "0.4.1", tamper=True)
    forged, _ = make_package(tmp_path, vendor_key, "0.4.2", bad_signature=True)
    page = panel.get("/painel/downloads").text
    assert "arquivo foi alterado" in page and "assinatura NÃO confere" in page and f'href="/painel/downloads/{tampered}"' not in page and f'href="/painel/downloads/{forged}"' not in page
    for n in (tampered, forged):
        r = panel.get(f"/painel/downloads/{n}")
        assert r.status_code == 303 and r.headers["location"] == "/painel/downloads"                              # recusado com aviso
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM lic_audit WHERE action = 'package.download'")).scalar() == 0


def test_download_never_serves_anything_outside_the_package_list(panel, tmp_path, vendor_key):
    login(panel)
    make_package(tmp_path, vendor_key)
    (tmp_path / "segredo.txt").write_text("nao entregar")
    outside = tmp_path.parent / "promptshield-onprem-fora.zip"
    outside.write_bytes(b"fora da pasta")
    for name in ("segredo.txt", "../segredo.txt", "..%2fsegredo.txt", "promptshield-onprem-fora.zip", "promptshield-onprem-0.4.0.zip.manifest.json",
                 "promptshield-onprem-..%2f..%2fetc%2fpasswd.zip", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "promptshield-onprem-0.4.0.zip/../../x"):
        assert panel.get(f"/painel/downloads/{name}").status_code in (404, 422, 307, 308), name
    assert panel.get("/painel/downloads/promptshield-onprem-0.4.0.zip/leia-me").status_code == 200
    assert panel.get("/painel/downloads/promptshield-onprem-9.9.9.zip/leia-me").status_code == 404


def test_no_signing_key_means_no_download(panel, tmp_path, vendor_key, monkeypatch):
    login(panel)
    name, _ = make_package(tmp_path, vendor_key)
    monkeypatch.setattr(settings, "license_signing_key", None)
    page = panel.get("/painel/downloads").text
    assert "LICENSE_SIGNING_KEY" in page and f'href="/painel/downloads/{name}"' not in page
    assert panel.get(f"/painel/downloads/{name}").status_code == 303


# ---------------------------------------------------------------- versões publicadas
def test_versions_page_publishes_only_with_confirmation_and_audits_with_the_admin_email(panel, tmp_path, vendor_key):
    from test_releases import app_package, rules_package
    login(panel)
    assert "Nenhum pacote na pasta" in panel.get("/painel/versoes").text
    name, _ = app_package(tmp_path, vendor_key, "0.4.0")
    rname, _ = rules_package(tmp_path, vendor_key, "2026.11.1")
    page = panel.get("/painel/versoes").text
    assert name in page and rname in page and "não publicada" in page and "assinatura confere" in page
    sem_confirmar = post(panel, "/painel/versoes/publicar", {"kind": "app", "file": name, "notes": "x"})
    assert sem_confirmar.status_code == 303
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM lic_releases")).scalar() == 0                      # sem a caixa, nada é publicado
    assert post(panel, "/painel/versoes/publicar", {"kind": "app", "file": name, "notes": "Corrige X", "security": "sim", "confirm": "sim"}).status_code == 303
    assert post(panel, "/painel/versoes/publicar", {"kind": "rules", "file": rname, "notes": "Regras novas", "confirm": "sim"}).status_code == 303
    page = panel.get("/painel/versoes").text
    assert page.count("publicada") >= 2 and "segurança" in page and "Corrige X" in page and f"por {EMAIL}" in page
    with session_scope() as s:
        rows = s.execute(text("SELECT kind, version, security FROM lic_releases ORDER BY kind")).all()
        actors = {e.actor for e in s.execute(select(AuditEntry).where(AuditEntry.action == "release.publish")).scalars()}
    assert [tuple(r) for r in rows] == [("app", "0.4.0", True), ("rules", "2026.11.1", False)] and actors == {EMAIL}
    rid = re.search(r'/painel/versoes/([0-9a-f-]{36})/retirar', page).group(1)
    assert post(panel, f"/painel/versoes/{rid}/retirar", {"reason": " "}).status_code == 303
    assert post(panel, f"/painel/versoes/{rid}/retirar", {"reason": "regressão"}).status_code == 303
    assert "retirada" in panel.get("/painel/versoes").text
    for path in ("/painel/versoes/publicar", f"/painel/versoes/{rid}/retirar"):
        assert panel.post(path, data={"csrf": "errado"}, headers=H).status_code == 403                      # CSRF também vale aqui


def test_dashboard_flags_outdated_installations_and_security_ones_louder(panel, tmp_path, vendor_key):
    from test_releases import app_package
    login(panel)
    cid = new_contract(panel)
    inst = activate_contract(cid, vendor_key)
    with session_scope() as s:
        s.execute(text("UPDATE lic_installations SET product_version = '0.3.0', update_state = 'app:ready(0.4.0)', last_seen_at = now()"))
        s.execute(text("UPDATE lic_authorizations SET issued_at = now()"))
    name, _ = app_package(tmp_path, vendor_key, "0.4.0")
    with session_scope() as s:
        service.publish_release(s, "app", name, "", False, service.utcnow(), actor=EMAIL)
    page = panel.get("/painel/visao-geral").text
    assert "Versão 0.3.0 instalada; a 0.4.0 está publicada." in page and "app:ready(0.4.0)" in page and "CORREÇÃO DE SEGURANÇA" not in page
    name2, _ = app_package(tmp_path, vendor_key, "0.4.1")
    with session_scope() as s:
        service.publish_release(s, "app", name2, "grave", True, service.utcnow(), actor=EMAIL)
    page = panel.get("/painel/visao-geral").text
    assert "a 0.4.1 está publicada (CORREÇÃO DE SEGURANÇA)" in page and "lv2" in page
    with session_scope() as s:
        s.execute(text("UPDATE lic_installations SET product_version = '0.4.1'"))
    assert "está publicada" not in panel.get("/painel/visao-geral").text                                    # atualizou: o alerta some
    assert inst is not None
