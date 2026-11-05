"""Importador de histórico. Transcrições SINTÉTICAS no formato observado (ver importer.py), nunca dados reais."""
import json
from pathlib import Path

from promptshield_claude_hook import client, importer, translate
from promptshield_claude_hook.config import Config

CFG = Config(api_url="http://localhost:1", api_key="ps_x", user_id="u1", device_id="d1")


def rec(**kw):
    base = {"sessionId": "s1", "timestamp": "2026-10-10T12:00:00.000Z", "uuid": "u-1", "isSidechain": False}
    return {**base, **kw}


PROMPT = rec(type="user", promptId="p1", message={"role": "user", "content": "SIMULADO: CPF 529.982.247-25"})
TOOL = rec(type="assistant", uuid="a1", message={"role": "assistant", "content": [
    {"type": "thinking", "thinking": "segredo do raciocínio"},
    {"type": "text", "text": "resposta simulada"},
    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "cat ~/.aws/credentials"}}]})
RESULT = rec(type="user", uuid="r1", message={"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "SIMULADO conteúdo de arquivo"}]})


def write(tmp: Path, records, junk=False) -> Path:
    d = tmp / "projeto-x"
    d.mkdir()
    lines = [json.dumps(r) for r in records] + (["{quebrado"] if junk else [])
    (d / "s1.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return tmp


def test_default_sends_only_prompts_and_tool_calls():
    assert [e["kind"] for e in importer.build_events(PROMPT, CFG)] == ["prompt"]
    ev = importer.build_events(TOOL, CFG)
    assert [e["kind"] for e in ev] == ["tool_call"]
    assert ev[0]["content"]["tool_input"]["command"].startswith("cat")
    assert importer.build_events(RESULT, CFG) == []
    assert "raciocínio" not in json.dumps(ev)  # thinking nunca é enviado


def test_opt_in_adds_responses_and_tool_results():
    kinds = [e["kind"] for e in importer.build_events(TOOL, CFG, responses=True)]
    assert kinds == ["response", "tool_call"]
    assert [e["kind"] for e in importer.build_events(RESULT, CFG, tool_results=True)] == ["tool_result"]


def test_event_ids_match_the_live_hook_formula_and_are_stable():
    live = translate.event_id_for({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt_id": "p1"})
    assert importer.build_events(PROMPT, CFG)[0]["event_id"] == live
    live_tool = translate.event_id_for({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_use_id": "toolu_1"})
    assert importer.build_events(TOOL, CFG)[0]["event_id"] == live_tool
    assert importer.build_events(TOOL, CFG)[0]["event_id"] == importer.build_events(TOOL, CFG)[0]["event_id"]


def test_event_is_labelled_experimental_import_with_original_time():
    e = importer.build_events(PROMPT, CFG)[0]
    assert e["source"] == {"channel": "agent_hook", "app": "claude_code_import", "integration_status": "experimental"}
    assert e["occurred_at"].startswith("2026-10-10T12:00:00")


def test_skips_injected_and_malformed_records():
    cmd = rec(type="user", promptId="p2", message={"role": "user", "content": "<local-command-stdout>x</local-command-stdout>"})
    meta = rec(type="user", promptId="p3", isMeta=True, message={"role": "user", "content": "texto"})
    nots = {"type": "user", "message": {"content": "sem sessão"}}
    assert importer.build_events(cmd, CFG) == [] and importer.build_events(meta, CFG) == [] and importer.build_events(nots, CFG) == []


def test_collect_counts_unreadable_lines_and_filters(tmp_path):
    root = write(tmp_path, [PROMPT, TOOL, RESULT, {"type": "mode"}], junk=True)
    events, stats = importer.collect(root, CFG, since=None, project=None, responses=False, tool_results=False)
    assert len(events) == 2 and stats["linhas ilegíveis"] == 1 and stats["registros ignorados"] == 2
    assert importer.collect(root, CFG, since=None, project="outro", responses=False, tool_results=False)[0] == []


def test_dry_run_sends_nothing(tmp_path, monkeypatch, capsys):
    root = write(tmp_path, [PROMPT, TOOL])
    monkeypatch.setattr(client, "post_event", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia enviar")))
    assert importer.main(["--path", str(root)], CFG) == 0
    assert "SIMULAÇÃO" in capsys.readouterr().out


def test_send_retries_on_429_and_stops_on_other_errors(monkeypatch):
    calls = []

    def fake(cfg, ev):
        calls.append(ev["event_id"])
        if len(calls) == 1:
            raise client.ApiError("limite", status=429, retry_after=0)
        return {"duplicate": False}

    monkeypatch.setattr(client, "post_event", fake)
    monkeypatch.setattr(importer.time, "sleep", lambda s: None)
    evs = importer.build_events(PROMPT, CFG) + importer.build_events(TOOL, CFG)
    assert importer.send(evs, CFG, 10, say=lambda *_: None) == {"enviados": 2}
    assert len(calls) == 3

    def boom(cfg, ev):
        raise client.ApiError("API respondeu 401", status=401)

    monkeypatch.setattr(client, "post_event", boom)
    assert importer.send(evs, CFG, 10, say=lambda *_: None) == {"falhas": 1}
