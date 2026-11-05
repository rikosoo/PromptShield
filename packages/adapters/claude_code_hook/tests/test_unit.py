import json
import socket
import threading

import pytest

from promptshield_claude_hook import cli, config, decide, translate

CFG = config.Config(api_url="http://127.0.0.1:1", api_key="ps_x", user_id="rafael", department="Engenharia", device_id="NB-1")


def hook(name, **kw):
    return {"session_id": "s1", "hook_event_name": name, "cwd": "/p", "permission_mode": "default", **kw}


# ---------- tradução ----------
def test_user_prompt_becomes_prompt_event():
    ev = translate.build_event(hook("UserPromptSubmit", prompt="oi", prompt_id="p-1"), CFG)
    assert ev["kind"] == "prompt" and ev["content"]["text"] == "oi"
    assert ev["source"] == {"channel": "agent_hook", "app": "claude_code", "integration_status": "partial"}
    assert ev["actor"] == {"user_id": "rafael", "device_id": "NB-1", "department": "Engenharia"}
    assert ev["context"] == {"session_id": "s1", "personal_account": False}


def test_bash_pretooluse_sends_the_command():
    ev = translate.build_event(hook("PreToolUse", tool_name="Bash", tool_input={"command": "rm -rf ~/x", "description": "d"}, tool_use_id="t1"), CFG)
    assert ev["kind"] == "tool_call" and ev["content"] == {"tool_name": "Bash", "tool_input": {"command": "rm -rf ~/x"}}


def test_write_tool_sends_path_and_written_content_but_not_extra_fields():
    ev = translate.build_event(hook("PreToolUse", tool_name="Write", tool_input={"file_path": "/etc/x", "content": "SEGREDO"}, tool_use_id="t2"), CFG)
    assert ev["content"]["tool_input"] == {"file_path": "/etc/x"} and ev["content"]["text"] == "SEGREDO"


def test_posttooluse_result_is_stringified():
    ev = translate.build_event(hook("PostToolUse", tool_name="Read", tool_input={}, tool_response={"file": {"content": "x"}}, tool_use_id="t3"), CFG)
    assert ev["kind"] == "tool_result" and "content" in ev["content"]["text"]


def test_unsupported_event_is_ignored():
    assert translate.build_event(hook("Stop"), CFG) is None


def test_event_id_is_deterministic_per_tool_use():
    a = translate.event_id_for(hook("PreToolUse", tool_use_id="t1"))
    assert a == translate.event_id_for(hook("PreToolUse", tool_use_id="t1"))
    assert a != translate.event_id_for(hook("PreToolUse", tool_use_id="t2"))
    assert translate.event_id_for(hook("PreToolUse")) != translate.event_id_for(hook("PreToolUse"))


def test_long_text_is_clipped():
    cfg = config.Config(api_url="x", api_key="y", max_text_chars=10, user_id="u")
    assert len(translate.build_event(hook("UserPromptSubmit", prompt="a" * 100), cfg)["content"]["text"]) == 10


# ---------- decisão -> saída ----------
R = lambda d, **kw: {"decision": d, "categories": [{"id": "segredo", "confidence": 0.97}], "masked_text": "chave AKIA****", **kw}  # noqa: E731


@pytest.mark.parametrize("decision", ["allow", "alert"])
@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse"])
def test_allow_and_alert_do_not_interfere(event, decision):
    assert decide.render(event, R(decision)) is None


def test_prompt_block_uses_decision_block():
    out = decide.render("UserPromptSubmit", R("block"))
    assert out["decision"] == "block" and "credenciais" in out["reason"]


def test_prompt_mask_blocks_and_suggests_masked_version_only():
    out = decide.render("UserPromptSubmit", R("mask", masked_text="CPF ***.***.***-25"))
    assert out["decision"] == "block" and "CPF ***.***.***-25" in out["reason"]


def test_pretooluse_mapping():
    assert decide.render("PreToolUse", R("block"))["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decide.render("PreToolUse", R("mask"))["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert decide.render("PreToolUse", R("ask_justification"))["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert decide.render("PreToolUse", R("block"))["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_posttooluse_only_block_interferes():
    assert decide.render("PostToolUse", R("block"))["decision"] == "block"
    assert decide.render("PostToolUse", R("mask")) is None


def test_failure_rendering():
    assert decide.render_failure("PreToolUse", "open", "x") is None
    assert decide.render_failure("PreToolUse", "closed", "x")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decide.render_failure("UserPromptSubmit", "closed", "x")["decision"] == "block"


# ---------- núcleo com API fora do ar ----------
def _cfg(tmp_path, mode):
    return config.Config(api_url="http://127.0.0.1:1", api_key="ps_x", user_id="u", fail_mode=mode,
                         timeout_seconds=1, spool_path=str(tmp_path / "spool.jsonl"))


def test_fail_open_allows_and_spools_metadata_without_content(tmp_path):
    cfg = _cfg(tmp_path, "open")
    out = cli.run_hook(json.dumps(hook("UserPromptSubmit", prompt="meu segredo AKIAZ7QW4XK2M9PLR3TN", prompt_id="p")), cfg)
    assert out is None
    line = (tmp_path / "spool.jsonl").read_text()
    assert "AKIA" not in line and "segredo" not in line
    row = json.loads(line)
    assert row["kind"] == "prompt" and row["text_length"] > 0 and row["event_id"]
    assert oct((tmp_path / "spool.jsonl").stat().st_mode & 0o777) == "0o600"


def test_fail_closed_blocks_and_does_not_spool(tmp_path):
    out = cli.run_hook(json.dumps(hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_use_id="t")), _cfg(tmp_path, "closed"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not (tmp_path / "spool.jsonl").exists()


def test_garbage_input_never_raises(tmp_path):
    assert cli.run_hook("não é json", _cfg(tmp_path, "open")) is None
    assert cli.run_hook("não é json", _cfg(tmp_path, "closed")) is not None


def test_timeout_when_api_accepts_but_never_answers(tmp_path):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    stop = threading.Event()
    conns = []

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conns.append(srv.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        cfg = _cfg(tmp_path, "closed")
        cfg.api_url = f"http://127.0.0.1:{srv.getsockname()[1]}"
        cfg.timeout_seconds = 0.5
        import time
        t0 = time.time()
        out = cli.run_hook(json.dumps(hook("UserPromptSubmit", prompt="oi", prompt_id="p")), cfg)
        assert out["decision"] == "block" and time.time() - t0 < 3
    finally:
        stop.set()
        for c in conns:
            c.close()
        srv.close()


def test_missing_config_fails_open_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTSHIELD_API_URL", raising=False)
    monkeypatch.delenv("PROMPTSHIELD_API_KEY", raising=False)
    monkeypatch.setenv("PROMPTSHIELD_HOOK_CONFIG", str(tmp_path / "nao-existe.json"))
    cfg = config.load()
    assert not cfg.usable and cfg.fail_mode == "open"
    assert cli.run_hook(json.dumps(hook("UserPromptSubmit", prompt="x")), cfg) is None


def test_config_file_and_env_precedence(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"api_url": "http://a/", "api_key": "k1", "fail_mode": "closed", "timeout_seconds": 2}))
    monkeypatch.setenv("PROMPTSHIELD_HOOK_CONFIG", str(p))
    monkeypatch.delenv("PROMPTSHIELD_API_KEY", raising=False)
    monkeypatch.delenv("PROMPTSHIELD_FAIL_MODE", raising=False)
    cfg = config.load()
    assert (cfg.api_url, cfg.api_key, cfg.fail_mode, cfg.timeout_seconds) == ("http://a", "k1", "closed", 2.0)
    monkeypatch.setenv("PROMPTSHIELD_API_KEY", "k2")
    monkeypatch.setenv("PROMPTSHIELD_FAIL_MODE", "open")
    cfg = config.load()
    assert (cfg.api_key, cfg.fail_mode) == ("k2", "open")
    monkeypatch.setenv("PROMPTSHIELD_FAIL_MODE", "banana")
    assert config.load().fail_mode == "open"


def test_config_accepts_utf8_bom_written_by_windows_powershell(tmp_path):
    from promptshield_claude_hook import config
    f = tmp_path / "hook.json"
    f.write_bytes(b"\xef\xbb\xbf" + b'{"api_url": "http://localhost:8000/", "api_key": "ps_x"}')
    cfg = config.load(str(f))
    assert cfg.api_url == "http://localhost:8000" and cfg.api_key == "ps_x" and cfg.usable


# ---------- GitHub Copilot CLI (formato lido em github/docs, hooks-reference.md; entradas SIMULADAS) ----------
def _ccfg():
    from promptshield_claude_hook.config import Config
    return Config(api_url="http://x", api_key="ps_x", user_id="u1", device_id="d1")


def test_copilot_prompt_and_shell_tool_events():
    from promptshield_claude_hook import translate
    p = translate.build_copilot_event("userPromptSubmitted", {"sessionId": "s", "timestamp": 1760000000000, "cwd": "/p", "prompt": "SIMULADO oi"}, _ccfg())
    assert p["kind"] == "prompt" and p["content"]["text"] == "SIMULADO oi" and p["source"]["app"] == "github_copilot_cli"
    assert p["source"]["integration_status"] == "experimental" and p["occurred_at"].startswith("2025-10-0")
    t = translate.build_copilot_event("preToolUse", {"sessionId": "s", "timestamp": 1760000000001, "toolName": "bash",
                                                     "toolArgs": '{"command": "rm -rf ~/x"}'}, _ccfg())
    assert t["kind"] == "tool_call" and t["content"]["tool_name"] == "Bash" and t["content"]["tool_input"]["command"] == "rm -rf ~/x"
    again = translate.build_copilot_event("preToolUse", {"sessionId": "s", "timestamp": 1760000000001, "toolName": "bash",
                                                         "toolArgs": '{"command": "rm -rf ~/x"}'}, _ccfg())
    assert again["event_id"] == t["event_id"]            # idempotente


def test_copilot_output_only_blocks_tools_and_never_prompts():
    from promptshield_claude_hook import decide
    block = {"decision": "block", "categories": [{"id": "shell_destrutivo", "confidence": 0.9}]}
    assert decide.render_copilot("preToolUse", block)["permissionDecision"] == "deny"
    assert decide.render_copilot("userPromptSubmitted", block) is None
    assert decide.render_copilot("preToolUse", {"decision": "allow"}) is None
    assert decide.render_copilot_failure("preToolUse", "closed", "x")["permissionDecision"] == "deny"
    assert decide.render_copilot_failure("preToolUse", "open", "x") is None


def test_copilot_cli_entrypoint_never_raises_and_fails_open(monkeypatch, tmp_path):
    from promptshield_claude_hook import cli
    cfg = _ccfg()
    cfg.spool_path = str(tmp_path / "s.jsonl")
    assert cli.run_copilot("preToolUse", "isto nao e json", cfg) is None
    cfg.fail_mode = "closed"
    assert cli.run_copilot("preToolUse", "isto nao e json", cfg)["permissionDecision"] == "deny"


def test_powershell_tool_sends_the_command_not_raw_json():
    from promptshield_claude_hook import translate
    c = translate._tool_content("PowerShell", {"command": "Get-Content $HOME\\.aws\\credentials", "description": "x"}, 1000)
    assert c == {"tool_name": "PowerShell", "tool_input": {"command": "Get-Content $HOME\\.aws\\credentials"}}


def test_inspection_stopped_by_license_never_blocks_even_in_fail_closed_and_says_so(tmp_path, capsys):
    """A API devolve 403 + cabeçalho quando a licença ou o contrato parou a inspeção: é decisão da empresa, não falha de rede."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(403)
            self.send_header("X-PromptShield-Inspection", "stopped")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = _cfg(tmp_path, "closed")
        cfg.api_url = f"http://127.0.0.1:{srv.server_address[1]}"
        out = cli.run_hook(json.dumps(hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_use_id="t")), cfg)
        assert out is None or out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"      # a ferramenta do usuário segue
        assert "PARADA" in capsys.readouterr().err
        assert not (tmp_path / "spool.jsonl").exists()
        # um 403 comum (sem o cabeçalho) continua sendo falha e segue o modo de falha
        class Plain(Handler):
            def do_POST(self):  # noqa: N802
                self.send_response(403)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        srv2 = http.server.HTTPServer(("127.0.0.1", 0), Plain)
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        cfg.api_url = f"http://127.0.0.1:{srv2.server_address[1]}"
        denied = cli.run_hook(json.dumps(hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_use_id="t")), cfg)
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        srv2.shutdown()
    finally:
        srv.shutdown()
