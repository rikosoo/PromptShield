"""Atualizações assistidas e pacotes de regras, ponta a ponta: o serviço do fornecedor REAL roda em processo (como em test_license_onprem) e o produto do cliente
avisa, o administrador aprova, o worker baixa e confere, e o pacote de regras passa por guardado -> sombra -> ativo -> retirado. Dados SINTÉTICOS."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import ADMIN_URL, event
from promptshield_licensing import (
    RULES_PRODUCT,
    generate_signing_key,
    sha256_file,
    sign_package,
    sign_rulepack,
)
from sqlalchemy import text
from test_license_onprem import Stub, activate, admin, down, lic  # noqa: F401  (fixture `lic` e ajudantes do teste de licenciamento)

pytestmark = pytest.mark.db
API_DIR = Path(__file__).resolve().parents[1]
DAY = timedelta(days=1)
SECRET_TEXT = "SIMULADO: usar XTK-ABCDEFGH12345678 no deploy"


@pytest.fixture(autouse=True)
def _clean(admin_engine, tmp_path, monkeypatch):
    from lic_service.config import settings as lsettings

    from app import rulepacks

    with admin_engine.begin() as c:
        c.execute(text("TRUNCATE update_state, rule_packs CASCADE"))
    pk = tmp_path / "pkgs"
    pk.mkdir()
    monkeypatch.setattr(lsettings, "packages_dir", str(pk))
    rulepacks.invalidate()
    yield pk
    rulepacks.invalidate()


def app_pkg(d, key, version="0.4.0", body=b"zip sintetico do cliente"):
    name = f"promptshield-onprem-{version}.zip"
    (d / name).write_bytes(body * 200 + version.encode())
    sha = sha256_file(d / name)
    (d / f"{name}.manifest.json").write_text(json.dumps({"version": version, "sha256": sha, "signature": sign_package(key, version, sha)}))
    return name


RULES = [{"id": "tok-interno-x", "category": "segredo", "confidence": 0.9, "rule": "Token interno do sistema X", "kind": "regex", "pattern": r"\bXTK-[A-Z0-9]{16}\b",
          "span_type": "xtk", "masked": "XTK-****"},
         {"id": "projeto-fenix", "category": "estrategia_ma", "confidence": 0.8, "rule": "Menção ao projeto Fênix", "kind": "terms", "terms": ["projeto fenix"]}]


def rules_pkg(d, key, version="2026.11.1", rules=None, weights=None):
    name = f"promptshield-rules-{version}.pack"
    payload = {"v": 1, "typ": "rulepack", "version": version, "min_engine": "2.0", "notes": "regras sintéticas", "weights": weights if weights is not None else {"segredo": 95},
               "rules": rules if rules is not None else RULES}
    (d / name).write_text(sign_rulepack(key, payload))
    sha = sha256_file(d / name)
    (d / f"{name}.manifest.json").write_text(json.dumps({"version": version, "sha256": sha, "signature": sign_package(key, version, sha, RULES_PRODUCT)}))
    return name


def vendor_publish(kind, name, notes="", security=False):
    from lic_service import service as lsvc
    from lic_service.db import session_scope

    with session_scope() as s:
        lsvc.publish_release(s, kind, name, notes, security, lsvc.utcnow(), actor="henrique@vendor.example")


def weekly(client, world, lic):                                           # noqa: F811
    if not getattr(lic, "_weekly", False):
        activate(client, world, lic, weekly=True)
        lic._weekly = True
    return lic


def validate(lic, **delta):                                               # noqa: F811
    from app import license_client

    license_client.invalidate()
    return license_client.renew(lic.clock.to(**delta))


def updates(client, world, who="admin"):
    return client.get("/v1/updates", headers=world.user(who))


def tick(lic):                                                            # noqa: F811
    from app import updates as upd

    return upd.tick(lic.clock.now)


def ingest(client, world, text_value=SECRET_TEXT):
    r = client.post("/v1/events", json=event(text_value), headers=world.key())
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- aviso de versão nova
def test_notices_arrive_with_the_validation_and_wait_for_the_admin(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    assert updates(client, world).json()["app"]["notice"] is None
    vendor_publish("app", app_pkg(_clean, lic.vendor_key), "Corrige uma falha grave", security=True)
    vendor_publish("rules", rules_pkg(_clean, lic.vendor_key), "Regras novas")
    validate(lic, days=7)
    u = updates(client, world).json()
    assert u["mode"] == "onprem" and u["app"]["installed"] == "0.3.0"
    n = u["app"]["notice"]
    assert (n["version"], n["security"], n["notes"], n["status"]) == ("0.4.0", True, "Corrige uma falha grave", "available")
    assert u["rules"]["notice"]["status"] == "available" and u["rules"]["notice"]["version"] == "2026.11.1"
    assert world.sql("SELECT count(*) FROM rule_packs").scalar() == 0                              # aviso não baixa nem instala nada
    assert not (Path(lic.dir) / "state" / "updates").exists() or not any((Path(lic.dir) / "state" / "updates").iterdir())
    for who in ("analista", "auditor", "leitura"):
        assert updates(client, world, who).status_code == 403                                      # só o administrador vê e decide
    # na validação seguinte o fornecedor fica sabendo o estado
    validate(lic, days=14)
    row = lic.vendor(lambda svc, s, k: s.execute(text("SELECT update_state, rules_version FROM lic_installations")).one())
    assert "app:available(0.4.0)" in row[0] and "rules:" in row[0]


def test_a_withdrawn_or_already_installed_version_disappears_and_old_versions_are_ignored(client, world, lic, _clean, monkeypatch):   # noqa: F811
    weekly(client, world, lic)
    vendor_publish("app", app_pkg(_clean, lic.vendor_key, "0.4.0"))
    validate(lic, days=7)
    assert updates(client, world).json()["app"]["notice"]["version"] == "0.4.0"
    from lic_service import service as lsvc
    from lic_service.db import session_scope
    from lic_service.models import Release

    with session_scope() as s:
        lsvc.withdraw_release(s, s.query(Release).one(), "regressão", lsvc.utcnow())
    validate(lic, days=14)
    assert updates(client, world).json()["app"]["notice"] is None                                  # retirada: o aviso some
    # o cliente já está numa versão MAIOR que a anunciada: o aviso é ignorado (nunca se volta atrás)
    vendor_publish("app", app_pkg(_clean, lic.vendor_key, "0.5.0"))
    from app.config import settings
    monkeypatch.setattr(settings, "version", "0.9.0")
    validate(lic, days=21)
    assert updates(client, world).json()["app"]["notice"] is None


def test_a_forged_notice_is_ignored_and_the_validation_itself_still_succeeds(client, world, lic):   # noqa: F811
    from promptshield_licensing import issue_notice
    from promptshield_licensing import sign_package as sp

    from app import license_client
    from app import updates as upd

    weekly(client, world, lic)
    evil = generate_signing_key()
    sha = "a" * 64
    forged = issue_notice(evil, kind="app", version="9.9.9", sha256=sha, size=10, security=True, notes="instale já", published_at=lic.clock.now,
                          package_signature=sp(evil, "9.9.9", sha), file="promptshield-onprem-9.9.9.zip")
    assert upd.record_notices({"app": forged, "rules": "lixo", "x": None}, lic.clock.now) == []
    assert updates(client, world).json()["app"]["notice"] is None
    license_client.invalidate()
    assert license_client.renew(lic.clock.to(days=7)).state.value == "ativo"                      # um aviso ruim nunca derruba a licença


# ---------------------------------------------------------------- aplicação: aprovar, baixar, conferir
def test_app_update_needs_approval_then_downloads_verified_and_is_never_installed_by_the_server(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    name = app_pkg(_clean, lic.vendor_key)
    vendor_publish("app", name, "Nova versão")
    validate(lic, days=7)
    assert tick(lic) == []                                                                         # sem aprovação, o worker não baixa nada
    for who in ("analista", "auditor", "leitura"):
        assert client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=world.user(who)).status_code == 403
    assert client.post("/v1/updates/app/approve", json={"version": "9.9.9"}, headers=admin(world)).status_code == 404
    assert client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=admin(world)).status_code == 200
    assert client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=admin(world)).status_code == 409          # já aprovada
    assert updates(client, world).json()["app"]["notice"]["status"] == "approved"
    assert tick(lic) == ["app:pronto(0.4.0)"]
    got = Path(lic.dir) / "state" / "updates" / name
    assert got.read_bytes() == (_clean / name).read_bytes() and not list(got.parent.glob("*.part"))
    n = updates(client, world).json()["app"]["notice"]
    assert (n["status"], n["approved_by"], n["sha256"]) == ("ready", "admin@a.example.com", sha256_file(got))
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'update.approve'").scalar() == 1
    assert world.sql("SELECT count(*) FROM events").scalar() == 0                                  # nada foi instalado nem executado: o servidor segue como estava
    out = subprocess.run([sys.executable, "-m", "app.cli", "update-ready"], cwd=API_DIR, capture_output=True, text=True,
                         env={**__import__("os").environ, "ADMIN_DATABASE_URL": ADMIN_URL, "DATABASE_URL": ADMIN_URL, "LICENSE_STATE_DIR": str(Path(lic.dir) / "state")})
    assert out.returncode == 0, out.stderr[-600:]
    info = json.loads(out.stdout)
    assert out.returncode == 0 and info["version"] == "0.4.0" and info["sha256"] == sha256_file(got) and info["file"] == name


def test_download_that_does_not_match_the_signed_hash_is_discarded_and_can_be_retried(client, world, lic, _clean):   # noqa: F811
    from app import license_client

    weekly(client, world, lic)
    name = app_pkg(_clean, lic.vendor_key)
    vendor_publish("app", name)
    validate(lic, days=7)
    client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=admin(world))

    class Corrupt(Stub):
        def stream(self, method, url, json=None, **kw):
            import contextlib

            class R:
                status_code = 200

                def iter_bytes(self, n):
                    yield b"conteudo corrompido no caminho"

                def read(self):
                    return b""

            return contextlib.nullcontext(R())

    real = license_client.http_factory
    license_client.http_factory = lambda: Corrupt(down)
    assert tick(lic) == ["app:falhou"]
    n = updates(client, world).json()["app"]["notice"]
    assert n["status"] == "failed" and ("maior que o anunciado" in n["error"] or "NÃO confere" in n["error"])
    updates_dir = Path(lic.dir) / "state" / "updates"
    assert not (updates_dir / name).exists() and not list(updates_dir.glob("*.part"))               # nada fica pela metade
    license_client.http_factory = real
    assert client.post("/v1/updates/retry", json={"kind": "app"}, headers=admin(world)).status_code == 200
    assert tick(lic) == ["app:pronto(0.4.0)"] and (updates_dir / name).is_file()


def test_the_vendor_refusing_the_download_is_reported_and_a_tampered_server_file_never_reaches_the_customer(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    name = app_pkg(_clean, lic.vendor_key)
    vendor_publish("app", name)
    validate(lic, days=7)
    (_clean / name).write_bytes(b"trocado na pasta do fornecedor depois de publicar")
    client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=admin(world))
    assert tick(lic) == ["app:falhou"]
    n = updates(client, world).json()["app"]["notice"]
    assert n["status"] == "failed" and "recusou" in n["error"] and "package_untrusted" in n["error"]
    assert not (Path(lic.dir) / "state" / "updates" / name).exists()
    validate(lic, days=14)
    row = lic.vendor(lambda svc, s, k: s.execute(text("SELECT update_state FROM lic_installations")).scalar())
    assert "app:failed(0.4.0)" in row                                                              # o fornecedor vê no painel que falhou


# ---------------------------------------------------------------- pacote de regras
def stage_rules(client, world, lic, _clean, **kw):   # noqa: F811
    weekly(client, world, lic)
    vendor_publish("rules", rules_pkg(_clean, lic.vendor_key, **kw), "regras sintéticas")
    validate(lic, days=7)
    assert tick(lic) == ["rules:guardado(2026.11.1)"]
    packs = updates(client, world).json()["packs"]
    assert len(packs) == 1 and packs[0]["status"] == "staged"
    return packs[0]["id"]


def phase(client, world, pid, to, who="admin"):
    return client.post(f"/v1/rule-packs/{pid}/phase", json={"to": to}, headers=world.user(who))


def test_rule_pack_is_downloaded_and_stored_without_any_effect_until_the_admin_decides(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    base = ingest(client, world)
    pid = stage_rules(client, world, lic, _clean)
    after = ingest(client, world)
    assert (after["categories"], after["risk"]["score"], after["masked_text"]) == (base["categories"], base["risk"]["score"], base["masked_text"])        # guardado: sem efeito
    d = client.get(f"/v1/rule-packs/{pid}", headers=admin(world)).json()
    assert d["version"] == "2026.11.1" and {r["id"] for r in d["rules"]} == {"tok-interno-x", "projeto-fenix"} and d["weights"] == {"segredo": 95}
    assert updates(client, world).json()["rules"]["notice"]["status"] == "staged"
    assert client.get(f"/v1/rule-packs/{pid}", headers=world.user("analista")).status_code == 403


def test_shadow_mode_records_hits_but_changes_nothing_then_active_applies_and_retire_restores(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    base = ingest(client, world)
    pid = stage_rules(client, world, lic, _clean)
    assert phase(client, world, pid, "active").status_code == 409                                   # não se pula a sombra
    assert phase(client, world, pid, "shadow", "analista").status_code == 403
    assert phase(client, world, pid, "shadow").json()["status"] == "shadow"
    shadow = ingest(client, world)
    assert (shadow["categories"], shadow["risk"]["score"], shadow["masked_text"]) == (base["categories"], base["risk"]["score"], base["masked_text"])
    flags = client.get(f"/v1/events/{shadow['event_id']}", headers=world.user("leitura")).json()["flags"]
    assert flags["pack"] == {"version": "2026.11.1", "mode": "shadow", "hits": ["tok-interno-x"]}
    ingest(client, world, "SIMULADO: falamos do projeto fenix ontem")
    hits = {r["id"]: r for r in client.get(f"/v1/rule-packs/{pid}", headers=admin(world)).json()["rules"]}
    assert (hits["tok-interno-x"]["hits_shadow"], hits["projeto-fenix"]["hits_shadow"], hits["tok-interno-x"]["hits_active"]) == (1, 1, 0)      # o administrador vê o impacto antes de valer
    # promover: passa a valer (categoria, máscara, motivo e o peso do pacote)
    assert phase(client, world, pid, "active").json()["status"] == "active"
    live = ingest(client, world)
    assert "segredo" in {c["id"] for c in live["categories"]} and "XTK-ABCDEFGH12345678" not in live["masked_text"] and "XTK-****" in live["masked_text"]
    assert live["risk"]["score"] > base["risk"]["score"] and any("Regra do pacote 2026.11.1" in r["rule"] for r in live["risk"]["reasons"])
    assert world.sql("SELECT sum(hits) FROM rule_pack_hits WHERE mode = 'active'").scalar() == 1
    # os pesos da empresa vencem os do pacote
    assert client.put("/v1/risk-weights", json={"weights": {"segredo": 10}}, headers=admin(world)).status_code == 200
    assert ingest(client, world)["risk"]["score"] < live["risk"]["score"]
    # desativar: volta ao padrão de fábrica, na hora
    assert phase(client, world, pid, "retired").json()["status"] == "retired"
    back = ingest(client, world)
    assert back["masked_text"] == base["masked_text"] and "XTK-ABCDEFGH12345678" in back["masked_text"]
    acts = [r[0] for r in world.sql("SELECT action FROM audit_log WHERE action LIKE 'rulepack.%' ORDER BY id").all()]
    assert acts == ["rulepack.shadow", "rulepack.active", "rulepack.retired"]                       # cada mudança de fase fica na auditoria


def test_only_one_pack_is_live_and_a_new_pack_replaces_the_old_one(client, world, lic, _clean):   # noqa: F811
    first = stage_rules(client, world, lic, _clean)
    assert phase(client, world, first, "shadow").status_code == 200
    vendor_publish("rules", rules_pkg(_clean, lic.vendor_key, "2026.12.1", weights={}), "segundo")
    validate(lic, days=14)
    assert tick(lic) == ["rules:guardado(2026.12.1)"]
    second = next(p["id"] for p in updates(client, world).json()["packs"] if p["version"] == "2026.12.1")
    assert phase(client, world, second, "shadow").status_code == 200
    status = {p["version"]: p["status"] for p in updates(client, world).json()["packs"]}
    assert status == {"2026.11.1": "retired", "2026.12.1": "shadow"}                               # só um por vez
    assert phase(client, world, first, "shadow").status_code == 200                                # um pacote retirado pode voltar à sombra
    assert phase(client, world, first, "bogus").status_code == 422 and phase(client, world, "00000000-0000-0000-0000-000000000000", "shadow").status_code == 404


def test_an_invalid_pack_is_refused_with_the_reasons_and_never_stored(client, world, lic, _clean):   # noqa: F811
    weekly(client, world, lic)
    bad = [{"id": "tok-interno-x", "category": "categoria_inventada", "confidence": 0.9, "rule": "regra com categoria que não existe", "kind": "regex", "pattern": r"(a+)+b"}]
    vendor_publish("rules", rules_pkg(_clean, lic.vendor_key, rules=bad))
    validate(lic, days=7)
    assert tick(lic) == ["rules:falhou"]
    n = updates(client, world).json()["rules"]["notice"]
    assert n["status"] == "failed" and "pacote recusado" in n["error"] and "taxonomia" in n["error"]
    assert world.sql("SELECT count(*) FROM rule_packs").scalar() == 0                              # nada foi guardado
    validate(lic, days=14)
    assert "rules:failed(2026.11.1)" in lic.vendor(lambda svc, s, k: s.execute(text("SELECT update_state FROM lic_installations")).scalar())


def test_a_tampered_rule_pack_in_the_database_is_ignored_and_the_factory_engine_keeps_working(client, world, lic, _clean, admin_engine):   # noqa: F811
    from app import rulepacks

    weekly(client, world, lic)
    base = ingest(client, world)
    pid = stage_rules(client, world, lic, _clean)
    phase(client, world, pid, "shadow")
    phase(client, world, pid, "active")
    assert "XTK-****" in ingest(client, world)["masked_text"]
    with admin_engine.begin() as c:                                                                # alguém com acesso ao banco troca o pacote por outro conteúdo
        c.execute(text("UPDATE rule_packs SET token = replace(token, 'pk1.', 'pk1.AAAA')"))
    rulepacks.invalidate()
    after = ingest(client, world)
    assert after["masked_text"] == base["masked_text"] and rulepacks.current() is None             # a assinatura não confere: ignorado, sem derrubar a análise


def test_license_off_means_no_updates_surface_at_all(client, world, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "license_mode", "off")
    assert client.get("/v1/updates", headers=admin(world)).json() == {"mode": "off"}
    assert client.post("/v1/updates/app/approve", json={"version": "0.4.0"}, headers=admin(world)).status_code == 404
    assert client.post("/v1/rule-packs/00000000-0000-0000-0000-000000000000/phase", json={"to": "shadow"}, headers=admin(world)).status_code == 404
