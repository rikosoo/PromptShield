"""O hook nunca pode sair com código diferente de 0 por defeito nosso ("Hook failed" no Codex), tem de ler UTF-8, e o comando do Codex
tem de ser válido em cmd, PowerShell e sh. Dados SINTÉTICOS."""
import io
import json
import subprocess
import sys

import pytest

from promptshield_claude_hook import cli, config, doctor, hooklog, setup, translate

CFG = config.Config(api_url="http://127.0.0.1:9", api_key="ps_aaaaaaaa_x", fail_mode="open", timeout_seconds=0.2)


class FakeStdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


@pytest.fixture(autouse=True)
def _log(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTSHIELD_HOOK_LOG", str(tmp_path / "hook.log"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PROMPTSHIELD_API_URL", CFG.api_url)
    monkeypatch.setenv("PROMPTSHIELD_API_KEY", CFG.api_key)
    monkeypatch.setenv("PROMPTSHIELD_TIMEOUT", "0.2")
    monkeypatch.setenv("PROMPTSHIELD_SPOOL_PATH", str(tmp_path / "spool.jsonl"))
    monkeypatch.delenv("PROMPTSHIELD_HOOK_CONFIG", raising=False)


def run_main(monkeypatch, capsys, raw: bytes, args: list[str]):
    monkeypatch.setattr(sys, "stdin", FakeStdin(raw))
    code = cli.main(args)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


@pytest.mark.parametrize("args", [[], ["--codex"], ["--copilot", "userPromptSubmitted"]])
def test_exit_code_is_always_zero_even_with_garbage_and_unreachable_server(monkeypatch, capsys, args):
    for raw in (b"", b"nao e json", b"\xff\xfe\x00\x81\x8d invalido", json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "oi è ação"}).encode()):
        code, out, _ = run_main(monkeypatch, capsys, raw, args)
        assert code == 0
        if out.strip():
            json.loads(out)                                     # o que sai no stdout é JSON válido
            assert out.isascii()                                # e só ASCII: nenhum console, em nenhuma página de código, falha ao escrever


def test_unexpected_crash_before_the_hook_runs_is_logged_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda *a, **k: (_ for _ in ()).throw(ValueError("config quebrada")))
    code, _, err = run_main(monkeypatch, capsys, b"{}", ["--codex"])
    assert code == 0 and "erro interno" in err
    line = json.loads(hooklog.tail(1)[0])
    assert line["error"].startswith("ValueError") and "config quebrada" in line["error"] and line["where"].endswith(".py:" + line["where"].split(":")[1])


def test_server_down_is_logged_without_prompt_text(monkeypatch, capsys):
    secret = "SIMULADO: texto que nao pode ir para o log 529.982.247-25"
    code, _, _ = run_main(monkeypatch, capsys, json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": secret}).encode(), ["--codex"])
    assert code == 0
    log = "\n".join(hooklog.tail(5))
    assert "codex_cli" in log and "UserPromptSubmit" in log
    assert "529.982" not in log and "texto que nao pode" not in log


def test_codex_event_without_a_prompt_field_logs_only_field_names(monkeypatch, capsys):
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "texto_do_usuario": "SIMULADO nao vai para o log", "turn_id": "t"}
    code, out, _ = run_main(monkeypatch, capsys, json.dumps(payload).encode(), ["--codex"])
    assert code == 0 and out.strip() == ""
    row = json.loads(hooklog.tail(1)[0])
    assert row["fields"] == ["hook_event_name", "session_id", "texto_do_usuario", "turn_id"]
    assert "SIMULADO" not in json.dumps(row)


@pytest.mark.parametrize("key", ["prompt", "user_prompt", "userPrompt", "input", "message", "text"])
def test_prompt_text_accepts_alternative_field_names(key):
    ev = translate.build_event({"hook_event_name": "UserPromptSubmit", key: "oi"}, CFG, "codex_cli")
    assert ev and ev["content"]["text"] == "oi" and ev["source"]["integration_status"] == "experimental"
    assert translate.build_event({"hook_event_name": "UserPromptSubmit", key: "   "}, CFG, "codex_cli") is None


@pytest.mark.parametrize("exe,args,expected", [
    ("C:\\Users\\Ana\\AppData\\Local\\Python\\python.exe", ["C:\\Users\\Ana\\.promptshield\\sensor\\promptshield-sensor.pyz", "--codex"],
     "C:\\Users\\Ana\\AppData\\Local\\Python\\python.exe C:\\Users\\Ana\\.promptshield\\sensor\\promptshield-sensor.pyz --codex"),
    ("/usr/bin/pythonX", ["-m", "promptshield_claude_hook", "--codex"], "/usr/bin/pythonX -m promptshield_claude_hook --codex"),
    ("/usr/bin/pythonX", ["/home/ana silva/sensor.pyz", "--codex"], '/usr/bin/pythonX "/home/ana silva/sensor.pyz" --codex'),
])
def test_shell_neutral_never_starts_with_a_quoted_string_when_it_can_avoid_it(monkeypatch, exe, args, expected):
    monkeypatch.setattr(setup, "_bare_python", lambda e: None)
    cmd = setup.shell_neutral(exe, args)
    assert cmd == expected and not cmd.startswith('"')          # PowerShell trata `"x" "y"` como erro de sintaxe


def test_shell_neutral_uses_bare_python_name_when_path_resolves_to_same_exe(monkeypatch):
    monkeypatch.setattr(setup, "_bare_python", lambda e: "python")
    assert setup.shell_neutral("C:\\Program Files\\Python312\\python.exe", ["C:\\a b\\x.pyz", "--codex"]) == 'python "C:\\a b\\x.pyz" --codex'


def test_only_a_python_path_with_spaces_outside_path_falls_back_to_quoted(monkeypatch):
    monkeypatch.setattr(setup, "_bare_python", lambda e: None)
    assert setup.shell_neutral("C:\\Program Files\\Python312\\python.exe", ["--codex"]).startswith('"C:\\Program Files')


def test_codex_hooks_json_command_has_no_quotes_around_flags():
    cmd = setup.codex_command()
    assert cmd.endswith(" --codex") and '"--codex"' not in cmd


def test_command_written_for_codex_actually_runs_through_sh_and_exits_zero(tmp_path, monkeypatch):
    """Roda de verdade o comando que o instalador grava, como o Codex faria (stdin = JSON), contra um servidor inalcançável (falha aberta)."""
    pyz_like = [sys.executable, "-m", "promptshield_claude_hook"]
    monkeypatch.setattr(setup, "self_command", lambda: (pyz_like[0], pyz_like[1:]))
    cmd = setup.codex_command()
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "SIMULADO: è ação"}, ensure_ascii=False).encode("utf-8")
    p = subprocess.run(cmd, input=payload, shell=True, capture_output=True, timeout=30)   # noqa: S602
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")


def test_doctor_runs_the_installed_commands_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "self_command", lambda: (sys.executable, ["-m", "promptshield_claude_hook"]))
    setup.write_settings(setup.codex_hooks_path(), setup.merge_codex({}))
    setup.write_settings(setup.copilot_hooks_path(), setup.copilot_doc())
    assert setup.claude_settings_path().parent != setup.codex_hooks_path().parent
    code = doctor.main([])
    out = capsys.readouterr().out
    assert "Codex CLI: hook em" in out and "[sh] OK (código 0)" in out and "GitHub Copilot CLI: hook em" in out
    assert "Claude Code: sem hook do PromptShield" in out
    assert "529.982" not in out and code in (0, 1)       # sem servidor, o resumo aponta o problema; os comandos em si rodaram
    assert "problema" in out                             # servidor 127.0.0.1:9 inalcançável aparece como PROBLEMA, não passa batido
