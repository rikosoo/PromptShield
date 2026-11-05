import json
import subprocess
import sys
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "install"


def run(script, root, *args):
    return subprocess.run(["sh", str(INSTALL / script), "--root", str(root), "--install-dir", "/opt/ps", *args],
                          capture_output=True, text=True, timeout=60)


def settings_path(root: Path) -> Path:
    for p in (root / "etc" / "claude-code" / "managed-settings.json",
              root / "Library" / "Application Support" / "ClaudeCode" / "managed-settings.json"):
        if p.exists():
            return p
    raise AssertionError("managed-settings.json não criado")


def test_install_merges_preserves_and_is_idempotent(tmp_path):
    first = run("install.sh", tmp_path, "--api-url", "http://api.exemplo.test", "--api-key", "ps_abc_def")
    assert first.returncode == 0, first.stderr
    sp = settings_path(tmp_path)
    data = json.loads(sp.read_text())
    sp.write_text(json.dumps({**data, "permissions": {"deny": ["Bash(rm -rf /)"]},
                              "hooks": {**data["hooks"], "Stop": [{"hooks": [{"type": "command", "command": "/x"}]}]}}))
    again = run("install.sh", tmp_path, "--api-url", "http://api.exemplo.test", "--api-key", "ps_abc_def", "--fail-mode", "closed")
    assert again.returncode == 0, again.stderr
    out = json.loads(sp.read_text())
    assert out["permissions"] == {"deny": ["Bash(rm -rf /)"]} and "Stop" in out["hooks"]        # preserva o que já havia
    for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        cmds = [h for g in out["hooks"][event] for h in g["hooks"]]
        assert len(cmds) == 1 and cmds[0]["command"] == "/opt/ps/promptshield-claude-hook" and cmds[0]["args"] == []
        assert cmds[0]["onFailure"] == "block"                                                  # fail-closed
    assert list(sp.parent.glob("managed-settings.json.bak-*"))
    assert "allowManagedHooksOnly" not in out                                                   # não liga por padrão


def test_installed_wrapper_runs_and_reports_config(tmp_path):
    assert run("install.sh", tmp_path, "--api-url", "http://127.0.0.1:1", "--api-key", "ps_a_b").returncode == 0
    cfg = next(p for p in tmp_path.rglob("claude-code-hook.json"))
    assert json.loads(cfg.read_text())["fail_mode"] == "open"
    wrapper = tmp_path / "opt" / "ps" / "promptshield-claude-hook"
    wrapper.write_text(wrapper.read_text().replace('"/opt/ps/lib', f'"{tmp_path}/opt/ps/lib'))   # o wrapper real usa o caminho sem --root
    r = subprocess.run([str(wrapper), "check"], capture_output=True, text=True, timeout=30, env={"PROMPTSHIELD_HOOK_CONFIG": str(cfg), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 1 and "FALHOU" in r.stdout                                           # API de teste fora do ar


def test_uninstall_removes_only_ours(tmp_path):
    run("install.sh", tmp_path, "--api-url", "http://a.test", "--api-key", "ps_a_b")
    sp = settings_path(tmp_path)
    data = json.loads(sp.read_text())
    data["permissions"] = {"allow": ["Bash(ls)"]}
    sp.write_text(json.dumps(data))
    assert run("uninstall.sh", tmp_path).returncode == 0
    left = json.loads(sp.read_text())
    assert left == {"permissions": {"allow": ["Bash(ls)"]}}
    assert not (tmp_path / "opt" / "ps" / "promptshield-claude-hook").exists()


def test_dry_run_writes_nothing(tmp_path):
    r = run("install.sh", tmp_path, "--api-url", "http://a.test", "--api-key", "ps_a_b", "--dry-run")
    assert r.returncode == 0 and "[dry-run]" in r.stdout and not any(tmp_path.rglob("*.json"))


def test_rejects_missing_args_and_bad_mode(tmp_path):
    assert run("install.sh", tmp_path).returncode == 2
    assert run("install.sh", tmp_path, "--api-url", "x", "--api-key", "y", "--fail-mode", "talvez").returncode == 2
    _ = sys
