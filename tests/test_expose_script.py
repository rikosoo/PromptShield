"""infra/expose.sh: portas configuráveis (porta alta), mensagens certas e recusa de portas inválidas. Usa um `docker` de mentira: nada sobe de verdade."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def box(tmp_path):
    (tmp_path / "infra").mkdir()
    shutil.copy(ROOT / "infra" / "expose.sh", tmp_path / "infra" / "expose.sh")
    (tmp_path / "bin").mkdir()
    fake = tmp_path / "bin" / "docker"
    fake.write_text('#!/bin/sh\n[ "$1" = info ] && exit 0\necho "docker $*"\n')
    fake.chmod(0o755)

    def run(env_text, *args, answer="entendi\n"):
        (tmp_path / ".env").write_text(env_text)
        env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
        r = subprocess.run(["bash", str(tmp_path / "infra" / "expose.sh"), *args], input=answer, text=True, capture_output=True, env=env, cwd=tmp_path)
        return r, (tmp_path / ".env").read_text()

    return run


def test_default_ports_and_only_the_console(box):
    r, env = box("POSTGRES_PASSWORD=x\n", "--public-ip", "203.0.113.9", "--web")
    assert r.returncode == 0, r.stderr
    assert "PUBLIC_BASE_URL=http://203.0.113.9:3000" in env and "WEB_BIND=0.0.0.0" in env and "API_BIND" not in env
    assert "Console: http://203.0.113.9:3000" in r.stdout and "libere TCP 3000 só" in r.stdout
    assert "API" not in r.stdout.split("ATENÇÃO")[1]                                      # abrir só o console não fala da API nem do texto original


def test_high_ports_from_the_env_are_used_everywhere(box):
    r, env = box("API_PORT=18000\nWEB_PORT=13000\n", "--public-ip", "203.0.113.9", "--web", "--api")
    assert r.returncode == 0, r.stderr
    assert "PUBLIC_BASE_URL=http://203.0.113.9:13000" in env and "API_BIND=0.0.0.0" in env
    assert "Console: http://203.0.113.9:13000" in r.stdout and "API: http://203.0.113.9:18000" in r.stdout
    assert "libere TCP 13000 e 18000 só" in r.stdout and "texto ORIGINAL" in r.stdout
    closed, env2 = box(env, "--close")
    assert closed.returncode == 0 and "PUBLIC_BASE_URL=http://localhost:13000" in env2 and "BIND" not in env2


def test_api_only_does_not_announce_a_console(box):
    r, _ = box("API_PORT=18000\n", "--public-ip", "203.0.113.9", "--api")
    assert r.returncode == 0 and "API: http://203.0.113.9:18000" in r.stdout and "Console:" not in r.stdout


@pytest.mark.parametrize("env_text, msg", [
    ("WEB_PORT=80\n", "fora de 1024-65535"), ("WEB_PORT=70000\n", "fora de 1024-65535"), ("WEB_PORT=abc\n", "porta inválida"),
    ("WEB_PORT=9000\nAPI_PORT=9000\n", "não podem ser iguais"),
])
def test_invalid_ports_are_refused_before_touching_anything(box, env_text, msg):
    r, env = box(env_text, "--public-ip", "203.0.113.9", "--web")
    assert r.returncode == 2 and msg in r.stderr
    assert env == env_text                                                               # o .env não foi alterado


def test_declining_changes_nothing(box):
    r, env = box("WEB_PORT=13000\n", "--public-ip", "203.0.113.9", "--web", answer="nao\n")
    assert r.returncode == 1 and env == "WEB_PORT=13000\n"
