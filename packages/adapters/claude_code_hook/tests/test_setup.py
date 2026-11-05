"""Assistente `setup`: funções puras e fluxo com entradas simuladas. Nada toca o ~/.claude nem o ~/.promptshield reais."""
import json
from pathlib import Path

import pytest

from promptshield_claude_hook import config, setup

CMD = "python"


def test_merge_keeps_user_hooks_is_idempotent_and_reversible():
    mine = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-script"}]}]}, "theme": "dark"}
    once = setup.merge_hooks(json.loads(json.dumps(mine)))
    twice = setup.merge_hooks(json.loads(json.dumps(once)))
    assert once == twice and setup.is_installed(once)
    assert once["theme"] == "dark"
    assert any(h.get("command") == "meu-script" for g in once["hooks"]["PreToolUse"] for h in g["hooks"])
    assert len(once["hooks"]["PreToolUse"]) == 2 and set(once["hooks"]) == set(setup.EVENTS)
    back = setup.remove_ours(once)
    assert back == mine and not setup.is_installed(back)


def test_merge_into_empty_and_shapes():
    d = setup.merge_hooks({})
    assert "matcher" not in d["hooks"]["UserPromptSubmit"][0] and d["hooks"]["PreToolUse"][0]["matcher"] == "*"
    e = d["hooks"]["PostToolUse"][0]["hooks"][0]
    assert e["type"] == "command" and e["args"] == ["-m", "promptshield_claude_hook"] and e["timeout"] == 10


def test_write_settings_makes_backup_no_bom_and_reads_bom(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir()
    p.write_bytes(b"\xef\xbb\xbf" + b'{"model": "x"}')
    data = setup.read_settings(p)
    assert data == {"model": "x"}
    backup = setup.write_settings(p, setup.merge_hooks(data))
    assert backup and backup.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf") and json.loads(p.read_text())["model"] == "x"


def test_refuses_to_touch_invalid_settings(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{quebrado")
    with pytest.raises(ValueError):
        setup.read_settings(p)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("PROMPTSHIELD_HOOK_CONFIG", raising=False)
    for k in ("PROMPTSHIELD_API_URL", "PROMPTSHIELD_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def wizard(answers, secrets=()):
    out, opened = [], []
    a, s = iter(answers), iter(secrets)
    w = setup.Wizard(ask=lambda p: next(a), secret=lambda p: next(s), say=lambda *x: out.append(" ".join(map(str, x))), open_url=opened.append)
    return w, out, opened


def test_default_user_config_is_found_without_env_var(env):
    setup.write_hook_config("http://localhost:8000/", "ps_abc", "Pessoal")
    cfg = config.load()
    assert cfg.usable and cfg.api_url == "http://localhost:8000" and cfg.department == "Pessoal"


def test_full_flow_links_claude_code_then_removes(env, monkeypatch):
    monkeypatch.setattr("promptshield_claude_hook.client.get_hook_config", lambda cfg: {"failure_mode": "open"})
    # 1 = Claude Code; URL padrão; colar chave; sem departamento; confirma; depois 7 = remover e confirma; 0 = sair
    w, out, _ = wizard(["1", "", "1", "", "sim", "7", "sim", "0"], secrets=["ps_teste123"])
    assert w.run() == 0
    text = "\n".join(out)
    assert "Claude Code vinculado" in text and "Removido" in text and "OK. Servidor respondeu" in text
    assert not setup.is_installed(setup.read_settings(setup.claude_settings_path()))
    assert json.loads(Path(config.user_config_path()).read_text())["api_key"] == "ps_teste123"


def test_declining_changes_nothing_including_codex(env):
    setup.write_hook_config("http://localhost:8000", "ps_x")
    w, out, _ = wizard(["1", "nao", "3", "nao", "0"])
    w.run()
    assert not setup.claude_settings_path().exists() and not setup.codex_hooks_path().exists()
    assert "Cancelado" in "\n".join(out)


def test_bad_key_is_not_saved_and_browser_option_opens_console(env):
    w, out, opened = wizard(["", "2", ""], secrets=["chave-errada"])
    w.claude_code()
    assert not Path(config.user_config_path()).exists() and opened == ["http://localhost:3000/privacy"]
    assert "ps_" in "\n".join(out)


def test_copilot_hooks_file_is_ours_only_and_removed_cleanly(env, monkeypatch):
    monkeypatch.setattr("promptshield_claude_hook.client.get_hook_config", lambda cfg: {"failure_mode": "open"})
    setup.write_hook_config("http://localhost:8000", "ps_x")
    w, out, _ = wizard(["2", "sim", "7", "sim", "0"])
    w.run()
    doc = setup.copilot_doc()
    assert doc["version"] == 1 and set(doc["hooks"]) == {"userPromptSubmitted", "preToolUse", "postToolUse"}
    e = doc["hooks"]["preToolUse"][0]
    assert "--copilot preToolUse" in e["bash"] and e["powershell"].startswith("& ") and e["timeoutSec"] == 10
    assert "Copilot CLI vinculado" in "\n".join(out) and not setup.copilot_hooks_path().exists()
