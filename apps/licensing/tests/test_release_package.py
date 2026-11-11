"""Pacote de instalação do cliente: estrutura, hashes, assinatura, reprodutibilidade, Compose e o instalador rodando com um Docker de mentira. SINTÉTICO."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml
from promptshield_licensing import generate_signing_key, public_key_b64, verify_package
from promptshield_licensing.crypto import private_pem

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("build_package", ROOT / "infra" / "release" / "build_package.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)           # type: ignore[union-attr]

import base64  # noqa: E402

KEY = generate_signing_key()
KEY_B64 = base64.b64encode(private_pem(KEY)).decode()
URL = "https://licencas.exemplo.com.br"
V = "0.4.0"


def make(tmp_path, **kw):
    kw.setdefault("with_source", False)
    return bp.build(V, URL, tmp_path / "out", signing_key=KEY_B64, root=ROOT, **kw)


def names(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return z.namelist()


def read(zip_path, member):
    with zipfile.ZipFile(zip_path) as z:
        return z.read(f"promptshield-onprem-{V}/{member}")


def test_package_has_everything_the_customer_needs_and_nothing_secret(tmp_path):
    res = make(tmp_path)
    n = {x.split("/", 1)[1] for x in names(res["zip"])}
    assert {"LEIA-ME.md", "VERSION", "docker-compose.yml", "env.example", "instalar.sh", "instalar.ps1", "backup.sh", "SHA256SUMS", "licenca/CHAVE_PUBLICA.txt"} <= n
    blob = b"".join(read(res["zip"], m) for m in n if m != "licenca/CHAVE_PUBLICA.txt")
    assert b"PRIVATE KEY" not in blob and KEY_B64.encode() not in blob                      # a chave privada nunca entra
    env = read(res["zip"], "env.example").decode()
    assert f"LICENSE_SERVER_URL={URL}" in env and f"LICENSE_PUBLIC_KEY={public_key_b64(KEY)}" in env and f"PS_VERSION={V}" in env
    assert "{{" not in blob.decode("utf-8", "ignore")                                      # nenhum marcador ficou sem valor
    assert read(res["zip"], "VERSION").decode().strip() == V
    assert "POSTGRES_PASSWORD=\n" in env and "LOCAL_AUTH_SECRET=\n" in env                  # senhas vazias: o instalador preenche com valores aleatórios


def test_checksums_manifest_and_signature_are_consistent(tmp_path):
    res = make(tmp_path)
    with zipfile.ZipFile(res["zip"]) as z:
        sums = z.read(f"promptshield-onprem-{V}/SHA256SUMS").decode().strip().splitlines()
        for line in sums:
            digest, rel = line.split("  ", 1)
            assert hashlib.sha256(z.read(f"promptshield-onprem-{V}/{rel}")).hexdigest() == digest, rel
        listed = {line.split("  ", 1)[1] for line in sums}
        assert listed == {x.split("/", 1)[1] for x in z.namelist()} - {"SHA256SUMS"}         # todos os arquivos estão na lista (menos ela mesma)
    out = tmp_path / "out"
    man = json.loads((out / f"promptshield-onprem-{V}.zip.manifest.json").read_text())
    assert man["sha256"] == res["sha256"] == hashlib.sha256(Path(res["zip"]).read_bytes()).hexdigest() and man["version"] == V
    assert verify_package(KEY.public_key(), V, man["sha256"], man["signature"])
    assert not verify_package(KEY.public_key(), "0.4.1", man["sha256"], man["signature"])
    assert (out / f"promptshield-onprem-{V}.README.md").read_text(encoding="utf-8") == read(res["zip"], "LEIA-ME.md").decode()


def test_zip_is_reproducible_and_scripts_are_executable(tmp_path):
    a = bp.build(V, URL, tmp_path / "a", signing_key=KEY_B64, root=ROOT, with_source=False)
    b = bp.build(V, URL, tmp_path / "b", signing_key=KEY_B64, root=ROOT, with_source=False)
    assert a["sha256"] == b["sha256"]                                                      # mesmo conteúdo, mesmo hash
    with zipfile.ZipFile(a["zip"]) as z:
        modes = {i.filename.rsplit("/", 1)[1]: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
    assert modes["instalar.sh"] == 0o755 and modes["backup.sh"] == 0o755 and modes["LEIA-ME.md"] == 0o644


def test_build_refuses_bad_input(tmp_path):
    for kw, msg in (({"version": "abc"}, "versão inválida"), ({"license_url": "http://x.example"}, "https"), ({"license_url": "licencas"}, "https"),
                    ({"signing_key": ""}, "chave de assinatura"), ({"signing_key": "lixo"}, "ilegível"), ({"version": "../0.4.0"}, "versão inválida")):
        args = dict(version=V, license_url=URL, signing_key=KEY_B64)
        args.update(kw)
        with pytest.raises(bp.BuildError, match=msg):
            bp.build(args.pop("version"), args.pop("license_url"), tmp_path / "x", root=ROOT, with_source=False, **args)
    assert bp.build(V, "http://localhost:8100", tmp_path / "ok", signing_key=KEY_B64, root=ROOT, with_source=False, allow_http=True)["version"] == V


def test_source_mode_ships_sources_without_junk(tmp_path):
    res = make(tmp_path, with_source=True)
    n = names(res["zip"])
    assert any(x.endswith("fontes/apps/api/Dockerfile") for x in n) and any(x.endswith("fontes/packages/detection/pyproject.toml") for x in n)
    assert not any("node_modules" in x or "__pycache__" in x or ".pyc" in x or "/.venv/" in x or "test-results" in x for x in n)


# ---------------------------------------------------------------- Compose do cliente
def customer_compose(tmp_path):
    res = make(tmp_path)
    return yaml.safe_load(read(res["zip"], "docker-compose.yml"))


def test_customer_compose_is_safe_and_has_no_vendor_parts(tmp_path):
    c = customer_compose(tmp_path)
    assert set(c["services"]) == {"db", "api", "worker", "web"} and c["name"] == "promptshield"
    assert "ports" not in c["services"]["db"]                                              # o banco nunca é exposto
    assert not any("profiles" in s for s in c["services"].values()) and "licensing" not in json.dumps(c).replace("licensedata", "")
    for name in ("api", "worker", "web", "db"):
        assert c["services"][name]["pull_policy"] == "never" and c["services"][name]["restart"] == "unless-stopped"
    for name in ("api", "worker"):
        assert c["services"][name]["image"] == "promptshield/api:${PS_VERSION:?defina no .env}"
    for name in ("api", "web"):
        assert all(p.startswith("${") and "127.0.0.1" in p for p in c["services"][name]["ports"])      # só o próprio servidor, por padrão
    api, worker, web = (c["services"][n]["environment"] for n in ("api", "worker", "web"))
    assert (api["OIDC_MODE"], api["LOCAL_AUTH"], web["AUTH_MODE"]) == ("off", "true", "local")               # sem login simulado
    assert api["LICENSE_MODE"] == worker["LICENSE_MODE"] == "onprem" and "ALLOW_HTTP" not in json.dumps(c)
    assert set(c["volumes"]) == {"licensedata", "pgdata"} and "licensedata:/var/lib/promptshield" in c["services"]["api"]["volumes"]


def test_customer_compose_only_uses_settings_the_product_knows(tmp_path):
    """Guarda contra divergência: toda variável do Compose do cliente existe no Compose do produto (ou é um nome conhecido do .env)."""
    c = customer_compose(tmp_path)
    repo = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for svc in ("api", "worker", "web"):
        mine, theirs = set(c["services"][svc]["environment"]), set(repo["services"][svc]["environment"])
        assert mine <= theirs, f"{svc}: {sorted(mine - theirs)}"
    from app.config import Settings
    known = {f.upper() for f in Settings.model_fields}
    for svc in ("api", "worker"):
        for var in c["services"][svc]["environment"]:
            assert var in known or var in {"APP_DB_PASSWORD"}, var                       # APP_DB_PASSWORD é do banco (migração), as demais são do produto


# ---------------------------------------------------------------- LEIA-ME
def test_readme_is_step_by_step_and_states_the_real_rules(tmp_path):
    txt = read(make(tmp_path)["zip"], "LEIA-ME.md").decode()
    for h in ("1. O que você precisa", "2. Confira o arquivo recebido", "3. Instale", "4. Primeiro acesso", "5. Deixar a equipe acessar (HTTPS)",
              "6. A validação da licença com o fornecedor", "7. Backup", "8. Atualizar", "9. Problemas comuns", "10. Parar, reiniciar e desinstalar", "11. Privacidade"):
        assert f"## {h}" in txt, h
    assert "licencas.exemplo.com.br" in txt and "bash instalar.sh" in txt and ".\\instalar.ps1" in txt and "bash backup.sh" in txt
    assert "10 dias" in txt and "21 dias" in txt and "toda semana" in txt and "se desfaz sozinha" in txt
    assert "Nunca" in txt and "down -v" in txt and "apaga o banco" in txt                  # o aviso sobre apagar dados está lá
    assert re.search(r"Nunca[^|]*enviados prompts", txt) or "**Nunca** são enviados prompts" in txt
    assert "{{" not in txt and "ainda não foi validado em campo" in txt                    # honestidade: o que não foi testado em campo


# ---------------------------------------------------------------- scripts
def test_shell_scripts_have_valid_syntax(tmp_path):
    res = make(tmp_path)
    d = tmp_path / "x"
    d.mkdir()
    for f in ("instalar.sh", "backup.sh"):
        (d / f).write_bytes(read(res["zip"], f))
        assert subprocess.run(["bash", "-n", str(d / f)], capture_output=True).returncode == 0, f
    assert b"\r\n" not in read(res["zip"], "instalar.sh")                                  # fim de linha Unix (senão o bash quebra)


STUB_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
case "$1 $2" in
  "info "*|"compose version") exit 0;;
esac
if [ "$1" = "load" ]; then exit 0; fi
if [ "$1 $2" = "compose up" ]; then exit 0; fi
case "$*" in
  *create-tenant*) [ -n "${STUB_FAIL_TENANT:-}" ] && exit 1; exit 0;;
  *set-password*) echo "Senha de ti@acme.example definida. Senha temporária (aparece só agora; a pessoa troca ao entrar): Tmp-Senha#1234";;
esac
exit 0
"""


def installed_dir(tmp_path, with_images=False):
    out = tmp_path / "pkg"
    if with_images:
        stub = tmp_path / "dockerbuild"
        stub.write_text('#!/usr/bin/env bash\necho "$*" >> "$STUB_LOG"\nif [ "$1" = "save" ]; then printf "imagem-sintetica"; fi\nexit 0\n')
        stub.chmod(0o755)
        os.environ["STUB_LOG"] = str(tmp_path / "build.log")
        res = bp.build(V, URL, out, signing_key=KEY_B64, root=ROOT, with_images=True, docker=str(stub))
    else:
        res = bp.build(V, URL, out, signing_key=KEY_B64, root=ROOT, with_source=False)
    dest = tmp_path / "cliente"
    with zipfile.ZipFile(res["zip"]) as z:
        z.extractall(dest)
        for i in z.infolist():
            (dest / i.filename).chmod((i.external_attr >> 16) & 0o777 or 0o644)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STUB_DOCKER)
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return dest / f"promptshield-onprem-{V}", bin_dir


def run_installer(d, bin_dir, tmp_path, **env):
    e = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_LOG": str(tmp_path / "docker.log"), "PS_EMPRESA": "Acme Ltda", "PS_ADMIN_EMAIL": "ti@acme.example", **env}
    return subprocess.run(["bash", "instalar.sh"], cwd=d, env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def test_installer_end_to_end_with_a_fake_docker(tmp_path):
    d, bin_dir = installed_dir(tmp_path)
    r = run_installer(d, bin_dir, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    env = dict(line.split("=", 1) for line in (d / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
    assert stat.S_IMODE((d / ".env").stat().st_mode) == 0o600                              # só o dono lê
    for k in ("POSTGRES_PASSWORD", "APP_DB_PASSWORD"):
        assert re.fullmatch(r"[0-9a-f]{48}", env[k]), k
    assert re.fullmatch(r"[0-9a-f]{96}", env["LOCAL_AUTH_SECRET"]) and len(env["LOCAL_AUTH_SECRET"]) >= 32          # a API exige 32+
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}=", env["ORIGINAL_TEXT_MASTER_KEY"])                                  # base64 urlsafe de 32 bytes
    assert len({env["POSTGRES_PASSWORD"], env["APP_DB_PASSWORD"], env["LOCAL_AUTH_SECRET"][:48]}) == 3               # valores diferentes
    assert env["LICENSE_SERVER_URL"] == URL and env["LICENSE_PUBLIC_KEY"] == public_key_b64(KEY) and env["PS_VERSION"] == V
    assert (d / ".instalado").is_file()
    assert "Tmp-Senha#1234" in r.stdout and "ti@acme.example" in r.stdout and "http://localhost:3000" in r.stdout and "CÓDIGO DE ATIVAÇÃO" in r.stdout
    log = (tmp_path / "docker.log").read_text()
    assert "compose up -d" in log and "create-tenant --name Acme Ltda --slug acme-ltda --admin-email ti@acme.example" in log and "set-password --email ti@acme.example --generate" in log
    assert "down" not in log and "-v" not in log.replace("-it", "")                                                  # nunca apaga volumes


def test_installer_is_safe_to_run_again(tmp_path):
    d, bin_dir = installed_dir(tmp_path)
    assert run_installer(d, bin_dir, tmp_path).returncode == 0
    before = (d / ".env").read_text()
    (tmp_path / "docker.log").write_text("")
    r = run_installer(d, bin_dir, tmp_path)
    assert r.returncode == 0 and (d / ".env").read_text() == before                        # senhas e chaves intactas
    assert "já foi configurado" in r.stdout and "Tmp-Senha" not in r.stdout
    log = (tmp_path / "docker.log").read_text()
    assert "create-tenant" not in log and "set-password" not in log                         # não recria a empresa nem troca a senha do administrador
    assert "compose up -d" in log


def test_installer_refuses_a_tampered_package_and_missing_docker_and_bad_input(tmp_path):
    d, bin_dir = installed_dir(tmp_path)
    (d / "docker-compose.yml").write_text((d / "docker-compose.yml").read_text() + "\n# alterado\n")
    r = run_installer(d, bin_dir, tmp_path)
    assert r.returncode != 0 and "não confere" in r.stderr and not (d / ".env").exists()   # parou ANTES de criar qualquer coisa
    d2, bin2 = installed_dir(tmp_path / "b")
    assert "e-mail" in run_installer(d2, bin2, tmp_path / "b", PS_ADMIN_EMAIL="sem-arroba").stderr.lower()
    r = run_installer(d2, bin2, tmp_path / "b", PS_EMPRESA="", PS_ADMIN_EMAIL="ti@acme.example")
    assert r.returncode != 0 and "Sem terminal interativo" in r.stderr
    d3, bin3 = installed_dir(tmp_path / "c")
    (bin3 / "docker").unlink()
    r = subprocess.run(["bash", "instalar.sh"], cwd=d3, env={"PATH": f"{bin3}:/usr/bin:/bin", "HOME": str(tmp_path)}, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode != 0 and ("Docker não encontrado" in r.stderr or "docker" in r.stderr.lower())


def test_installer_reports_when_the_company_cannot_be_created(tmp_path):
    d, bin_dir = installed_dir(tmp_path)
    r = run_installer(d, bin_dir, tmp_path, STUB_FAIL_TENANT="1")
    assert r.returncode != 0 and "Não consegui criar a empresa" in r.stderr and "set-password --email ti@acme.example" in r.stderr
    assert not (d / ".instalado").exists()                                                 # não marca como instalado


def test_images_mode_bundles_images_and_the_installer_loads_them(tmp_path):
    d, bin_dir = installed_dir(tmp_path, with_images=True)
    assert (d / "imagens" / f"promptshield-{V}.tar.gz").is_file() and not (d / "fontes").exists()
    build_log = (tmp_path / "build.log").read_text()
    assert f"build -f apps/api/Dockerfile -t promptshield/api:{V} ." in build_log and f"build -t promptshield/web:{V} apps/web" in build_log
    assert f"save promptshield/api:{V} promptshield/web:{V} postgres:16" in build_log        # as três imagens num arquivo só
    r = run_installer(d, bin_dir, tmp_path)
    assert r.returncode == 0 and f"docker load -i imagens/promptshield-{V}.tar.gz" in (tmp_path / "docker.log").read_text()
