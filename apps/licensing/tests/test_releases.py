"""Versões publicadas pelo fornecedor: publicar só o que confere, aviso assinado na validação e download protegido. PostgreSQL real, SINTÉTICO."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from promptshield_licensing import (
    RULES_PRODUCT,
    Installation,
    ReleaseError,
    build_request,
    sha256_file,
    sign_package,
    sign_rulepack,
    verify_notice,
    verify_rulepack,
)
from sqlalchemy import select, text
from test_service import T0, activate, refused, setup_contract

from lic_service import service
from lic_service.config import settings
from lic_service.db import session_scope
from lic_service.main import app
from lic_service.models import AuditEntry, Contract, Release
from lic_service.models import Installation as InstRow

pytestmark = pytest.mark.db
DAY = timedelta(days=1)


@pytest.fixture
def pkgdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "packages_dir", str(tmp_path))
    return tmp_path


def app_package(d, vendor_key, version="0.4.0", content=b"zip sintetico"):
    name = f"promptshield-onprem-{version}.zip"
    (d / name).write_bytes(content + version.encode())
    sha = sha256_file(d / name)
    (d / f"{name}.manifest.json").write_text(json.dumps({"version": version, "sha256": sha, "signature": sign_package(vendor_key, version, sha), "built_at": "2026-11-11T10:00:00Z"}))
    return name, sha


def rules_package(d, vendor_key, version="2026.11.1"):
    name = f"promptshield-rules-{version}.pack"
    (d / name).write_text(sign_rulepack(vendor_key, {"v": 1, "typ": "rulepack", "version": version, "rules": [{"id": "r-001"}]}))
    sha = sha256_file(d / name)
    (d / f"{name}.manifest.json").write_text(json.dumps({"version": version, "sha256": sha, "signature": sign_package(vendor_key, version, sha, RULES_PRODUCT), "built_at": "2026-11-11T10:00:00Z"}))
    return name, sha


def publish(kind, name, notes="", security=False, now=T0):
    with session_scope() as s:
        r = service.publish_release(s, kind, name, notes, security, now, actor="henrique@vendor.example")
        return type("Published", (), {"kind": r.kind, "version": r.version, "sha256": r.sha256})


def active_installation(vendor_key):
    cid, code = setup_contract()
    inst = Installation.create()
    activate(vendor_key, inst, code)
    return cid, inst


# ---------------------------------------------------------------- publicar
def test_only_signed_intact_and_newer_packages_can_be_published(pkgdir, vendor_key):
    name, sha = app_package(pkgdir, vendor_key, "0.4.0")
    rel = publish("app", name, "Primeira versão", security=False)
    assert (rel.kind, rel.version, rel.sha256) == ("app", "0.4.0", sha)
    with session_scope() as s:
        assert refused(lambda: service.publish_release(s, "app", name, "", False, T0)).code == "already_published"
        assert refused(lambda: service.publish_release(s, "app", "nao-existe.zip", "", False, T0)).code == "package_not_found"
        assert refused(lambda: service.publish_release(s, "tudo", name, "", False, T0)).code == "bad_kind"
    older, _ = app_package(pkgdir, vendor_key, "0.3.9")
    with session_scope() as s:
        assert refused(lambda: service.publish_release(s, "app", older, "", False, T0)).code == "not_newer"          # nunca se oferece versão anterior
    tampered, _ = app_package(pkgdir, vendor_key, "0.4.1")
    (pkgdir / tampered).write_bytes(b"trocado depois de assinado")
    forged, _ = app_package(pkgdir, vendor_key, "0.4.2")
    (pkgdir / f"{forged}.manifest.json").write_text(json.dumps({"version": "0.4.2", "sha256": sha256_file(pkgdir / forged), "signature": sign_package(vendor_key, "9.9.9", "0" * 64)}))
    with session_scope() as s:
        assert refused(lambda: service.publish_release(s, "app", tampered, "", False, T0)).code == "package_untrusted"
        assert refused(lambda: service.publish_release(s, "app", forged, "", False, T0)).code == "package_untrusted"
        assert s.execute(select(Release)).scalars().all().__len__() == 1


def test_app_and_rules_have_separate_domains_and_versions(pkgdir, vendor_key):
    a, _ = app_package(pkgdir, vendor_key, "0.4.0")
    r, _ = rules_package(pkgdir, vendor_key, "2026.11.1")
    publish("app", a)
    publish("rules", r)                                                                    # versão 2026.x na trilha de regras não conflita com 0.4.0 da aplicação
    with session_scope() as s:
        assert refused(lambda: service.publish_release(s, "app", r, "", False, T0)).code == "package_not_found"       # um pacote de regras nunca vira versão da aplicação
        assert refused(lambda: service.publish_release(s, "rules", a, "", False, T0)).code == "package_not_found"


def test_withdrawing_stops_the_notice_and_latest_is_the_highest_not_withdrawn(pkgdir, vendor_key):
    for v in ("0.4.0", "0.5.0", "0.10.0"):
        publish("app", app_package(pkgdir, vendor_key, v)[0])
    with session_scope() as s:
        assert service.latest_release(s, "app").version == "0.10.0"                           # 0.10.0 > 0.9 e 0.5 (ordem numérica, não de texto)
        top = s.execute(select(Release).where(Release.version == "0.10.0")).scalar_one()
        assert refused(lambda: service.withdraw_release(s, top, " ", T0)).code == "reason_required"
        service.withdraw_release(s, top, "regressão encontrada", T0, actor="henrique@vendor.example")
        assert refused(lambda: service.withdraw_release(s, top, "de novo", T0)).code == "already_withdrawn"
        assert service.latest_release(s, "app").version == "0.5.0"
        acts = [(e.actor, e.action) for e in s.execute(select(AuditEntry).where(AuditEntry.action.like("release.%")).order_by(AuditEntry.id)).scalars()]
    assert acts == [("henrique@vendor.example", "release.publish")] * 3 + [("henrique@vendor.example", "release.withdraw")]


# ---------------------------------------------------------------- avisos na validação
def renew_http(vendor_key, inst, now=None, **fields):
    c = TestClient(app)
    return c.post("/v1/renew", json={"request": build_request(inst, "renew", now or service.utcnow(), **fields)})


def test_renewal_carries_signed_notices_and_the_installation_reports_its_state(pkgdir, vendor_key):
    cid, inst = active_installation(vendor_key)
    first = renew_http(vendor_key, inst, version="0.3.0")
    assert first.status_code == 200 and first.json()["releases"] == {"app": None, "rules": None}              # nada publicado: nenhum aviso
    publish("app", app_package(pkgdir, vendor_key, "0.4.0")[0], "Corrige uma falha grave", security=True)
    publish("rules", rules_package(pkgdir, vendor_key, "2026.11.1")[0], "Novas regras")
    r = renew_http(vendor_key, inst, version="0.3.0", rules_version="2026.10.1", update_state="app:available")
    assert r.status_code == 200
    rel = r.json()["releases"]
    pub = vendor_key.public_key()
    app_n, rules_n = verify_notice(rel["app"], pub), verify_notice(rel["rules"], pub)
    assert (app_n.kind, app_n.version, app_n.security, app_n.notes) == ("app", "0.4.0", True, "Corrige uma falha grave")
    assert (rules_n.kind, rules_n.version, rules_n.security) == ("rules", "2026.11.1", False)
    with session_scope() as s:
        row = s.execute(select(InstRow)).scalar_one()
        assert (row.product_version, row.rules_version, row.update_state) == ("0.3.0", "2026.10.1", "app:available")
    with session_scope() as s:                                                                  # versão retirada some do aviso
        service.withdraw_release(s, s.execute(select(Release).where(Release.kind == "app")).scalar_one(), "retirada", T0)
    assert renew_http(vendor_key, inst, version="0.3.0").json()["releases"]["app"] is None


def test_notices_only_go_to_active_contracts_and_the_authorization_still_comes(pkgdir, vendor_key):
    cid, inst = active_installation(vendor_key)
    publish("app", app_package(pkgdir, vendor_key)[0])
    with session_scope() as s:
        service.close_contract(s, s.get(Contract, uuid.UUID(cid)), "cancelado", service.utcnow())
    r = renew_http(vendor_key, inst).json()
    assert r["releases"] == {"app": None, "rules": None} and r["authorization"].startswith("pl1.")      # encerrado: sem avisos, a autorização (encerrada) segue


def test_a_notice_for_one_key_is_useless_with_another(pkgdir, vendor_key):
    from promptshield_licensing import generate_signing_key
    cid, inst = active_installation(vendor_key)
    publish("app", app_package(pkgdir, vendor_key)[0])
    notice = renew_http(vendor_key, inst).json()["releases"]["app"]
    with pytest.raises(ReleaseError):
        verify_notice(notice, generate_signing_key().public_key())                          # um servidor falso não consegue forjar um aviso aceito


# ---------------------------------------------------------------- download
def download(inst, kind="app", version="0.4.0", now=None, client=None):
    c = client or TestClient(app)
    return c.post("/v1/releases/download", json={"request": build_request(inst, "download", now or service.utcnow(), kind=kind, version=version)})


def test_download_streams_the_exact_published_file_to_a_known_installation(pkgdir, vendor_key):
    cid, inst = active_installation(vendor_key)
    name, sha = app_package(pkgdir, vendor_key, "0.4.0", content=b"conteudo " * 5000)
    publish("app", name)
    r = download(inst)
    assert r.status_code == 200 and r.headers["x-content-sha256"] == sha and r.headers["cache-control"] == "no-store"
    assert (pkgdir / name).read_bytes() == r.content
    rname, rsha = rules_package(pkgdir, vendor_key)
    publish("rules", rname)
    rr = download(inst, "rules", "2026.11.1")
    assert rr.status_code == 200 and verify_rulepack(rr.text, vendor_key.public_key())["version"] == "2026.11.1"
    with session_scope() as s:
        assert [e.detail["version"] for e in s.execute(select(AuditEntry).where(AuditEntry.action == "release.download")).scalars()] == ["0.4.0", "2026.11.1"]


def test_download_refuses_strangers_replays_unpublished_withdrawn_closed_and_tampered(pkgdir, vendor_key):
    cid, inst = active_installation(vendor_key)
    name, _ = app_package(pkgdir, vendor_key, "0.4.0")
    publish("app", name)
    app_package(pkgdir, vendor_key, "0.5.0")                                                  # existe na pasta, mas NÃO foi publicado
    stranger = Installation.create()
    assert download(stranger).status_code == 403 and download(stranger).json()["code"] == "unknown_installation"
    assert download(inst, version="0.5.0").json()["code"] == "release_not_available"          # só o que foi publicado
    assert download(inst, version="9.9.9").status_code == 404
    c = TestClient(app)
    req = build_request(inst, "download", service.utcnow(), kind="app", version="0.4.0")
    assert c.post("/v1/releases/download", json={"request": req}).status_code == 200
    again = c.post("/v1/releases/download", json={"request": req})                           # o mesmo pedido capturado não vale duas vezes
    assert again.status_code == 400 and again.json()["code"] == "replay"
    old = build_request(inst, "download", service.utcnow() - timedelta(minutes=30), kind="app", version="0.4.0")
    assert c.post("/v1/releases/download", json={"request": old}).status_code == 400          # fora da janela de tempo
    renew_req = build_request(inst, "renew", service.utcnow())
    assert c.post("/v1/releases/download", json={"request": renew_req}).json()["code"] == "invalid_request"     # um pedido de outro tipo não serve
    for bad in ({"kind": "tudo"}, {"version": 5}):
        args = dict(kind="app", version="0.4.0")
        args.update(bad)
        assert c.post("/v1/releases/download", json={"request": build_request(inst, "download", service.utcnow(), **args)}).json()["code"] == "invalid_request"
    (pkgdir / name).write_bytes(b"alterado na pasta depois de publicar")                       # arquivo trocado: o servidor se recusa a entregar
    assert download(inst).json()["code"] == "package_untrusted"
    with session_scope() as s:
        refusals = {e.detail["code"] for e in s.execute(select(AuditEntry).where(AuditEntry.action == "download.refused")).scalars()}
    assert {"unknown_installation", "release_not_available", "replay", "invalid_request", "package_untrusted"} <= refusals
    app_package(pkgdir, vendor_key, "0.4.0")                                                  # restaura o arquivo
    with session_scope() as s:
        service.close_contract(s, s.get(Contract, uuid.UUID(cid)), "cancelado", service.utcnow())
    assert download(inst).json()["code"] == "contract_not_active"                             # contrato encerrado não baixa
    with session_scope() as s:
        service.reopen_contract(s, s.get(Contract, uuid.UUID(cid)), service.utcnow())
        service.withdraw_release(s, s.execute(select(Release)).scalar_one(), "retirada", service.utcnow())
    assert download(inst).json()["code"] == "release_not_available"                           # versão retirada deixa de ser entregue


def test_path_tricks_cannot_make_the_service_serve_other_files(pkgdir, vendor_key):
    cid, inst = active_installation(vendor_key)
    name, _ = app_package(pkgdir, vendor_key, "0.4.0")
    publish("app", name)
    (pkgdir / "segredo.txt").write_text("nao entregar")
    with session_scope() as s:
        s.execute(text("UPDATE lic_releases SET file_name = '../segredo.txt'"))                 # mesmo que o banco fosse adulterado, o nome não vira caminho
    assert download(inst).json()["code"] == "package_untrusted"
