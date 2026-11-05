"""O sensor é PASSIVO: nunca bloqueia, nunca pede confirmação e nunca interrompe a ferramenta, nem com a API fora do ar e fail_mode closed."""
import json
import sys

import pytest

from promptshield_claude_hook import cli, config, decide

pytestmark = pytest.mark.passive

BLOCKING = {"decision": "block", "would_decide": "block", "categories": [{"id": "segredo", "confidence": 0.97}], "masked_text": "x"}


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse"])
@pytest.mark.parametrize("decision", ["block", "mask", "ask_justification"])
def test_even_if_the_server_said_block_the_sensor_stays_silent(event, decision):
    assert decide.render(event, {**BLOCKING, "decision": decision}) is None
    assert decide.render_copilot(event[0].lower() + event[1:], {**BLOCKING, "decision": decision}) is None


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse", "preToolUse"])
def test_api_down_with_fail_mode_closed_never_blocks(event):
    assert decide.render_failure(event, "closed", "API fora do ar") is None
    assert decide.render_copilot_failure(event, "closed", "API fora do ar") is None


def test_end_to_end_with_unreachable_server_and_closed_mode_prints_nothing_and_exits_zero(monkeypatch, capsys, tmp_path):
    import io
    monkeypatch.setenv("PROMPTSHIELD_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PROMPTSHIELD_API_KEY", "ps_aaaaaaaa_x")
    monkeypatch.setenv("PROMPTSHIELD_FAIL_MODE", "closed")
    monkeypatch.setenv("PROMPTSHIELD_TIMEOUT", "0.2")
    monkeypatch.setenv("PROMPTSHIELD_SPOOL_PATH", str(tmp_path / "spool.jsonl"))
    monkeypatch.setenv("PROMPTSHIELD_HOOK_LOG", str(tmp_path / "hook.log"))
    assert config.load().fail_mode == "closed"
    for ev in ("UserPromptSubmit", "PreToolUse"):
        monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(json.dumps({"hook_event_name": ev, "prompt": "oi", "tool_name": "Bash",
                                                                                          "tool_input": {"command": "ls"}}).encode())})())
        assert cli.main([]) == 0
        assert capsys.readouterr().out.strip() == ""            # nada que faça o Claude Code bloquear, perguntar ou parar
