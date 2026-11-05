"""Escolha das IAs por números. Nada aqui toca arquivos reais do usuário."""
import json

import pytest

from promptshield_claude_hook import deploy, ias, setup

NAMES = ["ChatGPT", "Copilot (web", "Gemini", "Claude (web", "Claude Code", "Codex (CLI)", "GitHub Copilot CLI"]


def test_only_the_seven_supported_options_are_in_the_list_in_order_and_no_desktop_apps():
    text = ias.render_list()
    for i, name in enumerate(NAMES, 1):
        assert any(line.strip().startswith(f"{i})") and name in line for line in text.splitlines()), (i, name)
    assert "separados por vírgula" in text and "desktop" not in text.lower() and len(ias.CATALOG) == 7


@pytest.mark.parametrize("raw,expected", [("1,2,5", [1, 2, 5]), (" 5 , 1 ,1", [1, 5]), ("1;3", [1, 3]), ("todas", list(range(1, 8))), ("TODAS", list(range(1, 8)))])
def test_parse_accepts_commas_spaces_and_all(raw, expected):
    assert ias.parse_selection(raw) == (expected, [])


@pytest.mark.parametrize("raw", ["", "abc", "1,x", "0", "8", "10", "1,99", "1.5"])
def test_parse_rejects_bad_input_with_a_message(raw):
    nums, errs = ias.parse_selection(raw)
    assert nums == [] and errs


def test_every_option_has_an_honest_state_and_a_guide_and_manual_ones_do_not_auto_install():
    assert {i.state for i in ias.CATALOG} <= {ias.AUTO, ias.EXT, ias.MANUAL, ias.NONE}
    for i in ias.CATALOG:
        assert i.status and ias.guide(i.n)
    assert all(i.tool for i in ias.CATALOG)                 # só sobraram IAs que o sensor realmente cobre (os apps de desktop saíram)
    assert ias.BY_N[6].state == ias.AUTO and ias.BY_N[6].tool == "codex_cli"      # Codex CLI: hooks.json, EXPERIMENTAL
    assert "EXPERIMENTAL" in ias.BY_N[6].status and "A VERIFICAR" in ias.BY_N[6].status
    assert ias.tools_for([1, 2, 3, 4]) == ["browser_extension"] and ias.tools_for([5, 4, 1]) == ["claude_code", "browser_extension"]
    assert ias.tools_for([6]) == ["codex_cli"] and ias.tools_for([7]) == ["github_copilot_cli"]


def test_tested_label_only_where_the_owner_saw_it_work_on_a_real_machine():
    """ChatGPT e Gemini (web) apareceram no console do dono; Claude Code é a integração mais testada; o resto continua experimental."""
    assert {i.name.split(" (")[0] for i in ias.CATALOG if i.tested} == {"ChatGPT", "Gemini", "Claude Code"}
    text = ias.render_list()
    for line in text.splitlines():
        if line.strip().startswith(("1)", "3)", "5)")):
            assert "testado" in line and "experimental" not in line
        if line.strip().startswith(("2)", "4)", "6)", "7)")):
            assert "experimental" in line and "testado" not in line


def test_wizard_choice_flow_configures_only_what_is_automatic(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "copilot"))
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    for k in ("PROMPTSHIELD_HOOK_CONFIG", "PROMPTSHIELD_API_URL", "PROMPTSHIELD_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    setup.write_hook_config("http://localhost:8000", "ps_x")
    monkeypatch.setattr("promptshield_claude_hook.client.get_hook_config", lambda cfg: {"failure_mode": "open"})
    prepared = []
    monkeypatch.setattr(setup.browser, "install_extension", lambda *a, **k: prepared.append(a) or tmp_path)
    out, answers = [], iter(["5, 6 ,7, 1"] + ["sim"] * 6)
    w = setup.Wizard(ask=lambda p: next(answers), secret=lambda p: "", say=lambda *x: out.append(" ".join(map(str, x))), open_url=lambda u: None)
    w.choose()
    text = "\n".join(out)
    assert setup.is_installed(setup.read_settings(setup.claude_settings_path()))        # 5: automático
    assert prepared and setup.copilot_hooks_path().exists()                            # 1: extensão preparada; 7: Copilot CLI automático
    assert "[6] Codex (CLI): AUTOMÁTICO" in text and "[7] GitHub Copilot CLI (terminal): AUTOMÁTICO" in text and "Resumo" in text
    assert "extensão" in text.lower()


def test_wizard_choice_reasks_on_bad_input_and_gives_up_after_three(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    out, answers = [], iter(["x", "99", ""])
    w = setup.Wizard(ask=lambda p: next(answers), secret=lambda p: "", say=lambda *x: out.append(" ".join(map(str, x))), open_url=lambda u: None)
    w.choose()
    assert "Nada selecionado." in "\n".join(out)


def test_deploy_ias_flag_prints_guides_and_maps_tools(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "enroll", lambda url, token, tools, ias_keys=None: {"api_key": "ps_m"})
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    monkeypatch.setattr(deploy.browser, "install_extension", lambda *a, **k: tmp_path)
    assert deploy.main(["--list-ias"]) == 0 and "Quais IAs" in capsys.readouterr().out
    rc = deploy.main(["--api-url", "http://x", "--token", "pse_t", "--ias", "5,6", "--confirm-employees-notified", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "[6] Codex (CLI): AUTOMÁTICO" in out and "[5] Claude Code (CLI, terminal): AUTOMÁTICO" in out
    p = deploy.paths(tmp_path)
    assert setup.is_installed(json.loads(p["claude"].read_text())) and not p["copilot"].exists()
    assert deploy.main(["--api-url", "http://x", "--token", "pse_t", "--ias", "0", "--confirm-employees-notified", "--root", str(tmp_path)]) == 2


def test_docs_list_every_option():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[4] / "docs" / "guia-ias.md").read_text(encoding="utf-8")
    for i in ias.CATALOG:
        assert f"| {i.n} |" in doc and i.name.split(" (")[0] in doc, i.name


def test_every_ia_has_a_stable_key_the_server_accepts():
    import re
    assert set(ias.KEY) == set(ias.BY_N)                                           # nenhuma IA do catálogo fica sem identificador
    assert len(set(ias.KEY.values())) == len(ias.KEY)
    assert all(re.fullmatch(r"[a-z0-9_]{2,40}", k) for k in ias.KEY.values())      # o mesmo padrão que a API valida
    assert ias.keys_for([4, 1, 5]) == ["claude_web", "chatgpt_web", "claude_code"]
    # onde a IA gera eventos, o identificador é o `source.app` do evento (o painel liga uma coisa à outra)
    assert {ias.KEY[1], ias.KEY[2], ias.KEY[3], ias.KEY[4], ias.KEY[5], ias.KEY[7]} == {
        "chatgpt_web", "copilot_web", "gemini_web", "claude_code", "github_copilot_cli", "claude_web"}


def test_deploy_sends_the_chosen_ias_to_the_server(tmp_path, monkeypatch):
    seen = {}

    def fake_enroll(url, token, tools, ias_keys=None):
        seen["tools"], seen["ias"] = tools, ias_keys
        return {"api_key": "ps_m"}

    monkeypatch.setattr(deploy, "enroll", fake_enroll)
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    monkeypatch.setattr(deploy.browser, "install_extension", lambda *a, **k: tmp_path)
    assert deploy.main(["--api-url", "http://x", "--token", "pse_t", "--ias", "6,1,5", "--confirm-employees-notified", "--root", str(tmp_path)]) == 0
    assert seen["ias"] == ["chatgpt_web", "claude_code", "codex_cli"] and seen["tools"] == ["browser_extension", "claude_code", "codex_cli"]
    seen.clear()
    assert deploy.main(["--api-url", "http://x", "--token", "pse_t", "--tools", "claude_code", "--force", "--confirm-employees-notified",
                        "--root", str(tmp_path)]) == 0
    assert seen["ias"] is None                                                       # sem --ias, o sensor não inventa quais IAs são


def test_enroll_body_carries_ias_only_when_given(monkeypatch):
    import io
    bodies = []

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        bodies.append(json.loads(req.data))
        return Resp(json.dumps({"api_key": "ps_ok"}).encode())

    monkeypatch.setattr(deploy.urllib.request, "urlopen", fake_urlopen)
    deploy.enroll("http://x", "pse_t", ["claude_code"], ias_keys=["claude_code", "gemini_web"])
    deploy.enroll("http://x", "pse_t", ["claude_code"])
    assert bodies[0]["ias"] == ["claude_code", "gemini_web"] and "ias" not in bodies[1]


def test_wizard_reports_choices_with_add_and_survives_a_failed_report(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    for k in ("PROMPTSHIELD_HOOK_CONFIG", "PROMPTSHIELD_API_URL", "PROMPTSHIELD_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    setup.write_hook_config("http://localhost:8000", "ps_x")
    monkeypatch.setattr("promptshield_claude_hook.client.get_hook_config", lambda cfg: {"failure_mode": "open"})
    sent = []
    monkeypatch.setattr("promptshield_claude_hook.client.put_ias", lambda cfg, keys, mode="add": sent.append((keys, mode)) or {"ias": keys})
    out, answers = [], iter(["5, 4", "sim", "0"])
    w = setup.Wizard(ask=lambda p: next(answers), secret=lambda p: "", say=lambda *x: out.append(" ".join(map(str, x))), open_url=lambda u: None)
    w.choose()
    assert sent == [(["claude_web", "claude_code"], "add")] and "painel de Sensores" in "\n".join(out)

    def broken(cfg, keys, mode="add"):
        raise client_mod.ApiError("API indisponível")

    from promptshield_claude_hook import client as client_mod
    monkeypatch.setattr(client_mod, "put_ias", broken)
    out2, answers2 = [], iter(["5", "sim", "0"])
    w2 = setup.Wizard(ask=lambda p: next(answers2), secret=lambda p: "", say=lambda *x: out2.append(" ".join(map(str, x))), open_url=lambda u: None)
    w2.choose()
    assert "não consegui registrar" in "\n".join(out2) and "Resumo" in "\n".join(out2)               # o resto do assistente continua


def test_client_put_ias_sends_a_put_with_the_key_and_the_mode(monkeypatch):
    import io

    from promptshield_claude_hook import client as c
    from promptshield_claude_hook.config import Config
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        seen.update(method=req.get_method(), url=req.full_url, body=json.loads(req.data), key=req.get_header("X-api-key"))
        return Resp(b'{"ias": ["claude_code"]}')

    monkeypatch.setattr(c.urllib.request, "urlopen", fake_urlopen)
    out = c.put_ias(Config(api_url="http://x", api_key="ps_k"), ["claude_code"], "add")
    assert out == {"ias": ["claude_code"]} and seen == {"method": "PUT", "url": "http://x/v1/device/ias", "body": {"ias": ["claude_code"], "mode": "add"}, "key": "ps_k"}


def _enrolled(tmp_path, url="http://servidor:8000/"):
    p = deploy.paths(tmp_path)
    p["config"].parent.mkdir(parents=True, exist_ok=True)
    p["config"].write_text(json.dumps({"api_url": url, "api_key": "ps_ja_existe", "fail_mode": "open"}))
    return p


def test_reinstalling_on_an_enrolled_machine_reports_the_ias_with_the_existing_key(tmp_path, monkeypatch, capsys):
    """Mesmo servidor: não re-matricula (não gasta token nem vaga), mas as IAs escolhidas chegam ao painel Sensores."""
    _enrolled(tmp_path)
    monkeypatch.setattr(deploy, "enroll", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não pode re-matricular")))
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    seen = []
    monkeypatch.setattr(deploy.client, "put_ias", lambda cfg, keys, mode="add": seen.append((cfg.api_url, cfg.api_key, keys, mode)) or {"ias": keys})
    rc = deploy.main(["--api-url", "http://servidor:8000", "--token", "pse_t", "--ias", "5,1", "--confirm-employees-notified", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "já está matriculada" in out and "IAs informadas ao servidor" in out
    assert seen == [("http://servidor:8000", "ps_ja_existe", ["chatgpt_web", "claude_code"], "set")]
    seen.clear()    # sem --ias não chama o servidor à toa
    assert deploy.main(["--api-url", "http://servidor:8000", "--token", "pse_t", "--tools", "claude_code", "--confirm-employees-notified", "--root", str(tmp_path)]) == 0
    assert seen == []


def test_a_different_server_address_with_a_token_enrolls_again(tmp_path, monkeypatch, capsys):
    """Caso real do teste na AWS: a máquina tinha chave de outro endereço; o instalador de uma linha precisa funcionar sem --force."""
    p = _enrolled(tmp_path, "http://antigo:8000")
    calls = []
    monkeypatch.setattr(deploy, "enroll", lambda url, token, tools, **k: calls.append((url, token)) or {"api_key": "ps_nova"})
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    rc = deploy.main(["--api-url", "http://novo:8000", "--token", "pse_t", "--tools", "claude_code", "--confirm-employees-notified", "--root", str(tmp_path)])
    cfg = json.loads(p["config"].read_text())
    assert rc == 0 and calls == [("http://novo:8000", "pse_t")] and cfg["api_url"] == "http://novo:8000" and cfg["api_key"] == "ps_nova"
    assert "endereço mudou" in capsys.readouterr().out


def test_a_dead_old_key_falls_back_to_enrolling_when_a_token_is_given(tmp_path, monkeypatch, capsys):
    p = _enrolled(tmp_path)
    monkeypatch.setattr(deploy, "enroll", lambda *a, **k: {"api_key": "ps_nova"})
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    monkeypatch.setattr(deploy.client, "put_ias", lambda cfg, keys, mode="add": (_ for _ in ()).throw(deploy.client.ApiError("API indisponível")))
    assert deploy.main(["--api-url", "http://servidor:8000", "--token", "pse_t", "--ias", "6", "--confirm-employees-notified", "--root", str(tmp_path)]) == 0
    assert json.loads(p["config"].read_text())["api_key"] == "ps_nova" and "matriculando de novo" in capsys.readouterr().out


# ---------- Codex CLI (hooks.json) ----------
def test_codex_hooks_json_is_merged_without_touching_user_hooks_and_is_idempotent(tmp_path):
    from promptshield_claude_hook import setup
    mine = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 ~/meu_hook.py"}]}]}, "description": "meu"}
    once = setup.merge_codex(json.loads(json.dumps(mine)))
    twice = setup.merge_codex(json.loads(json.dumps(once)))
    assert once == twice and once["description"] == "meu"
    ups = once["hooks"]["UserPromptSubmit"]
    assert ups[0] == mine["hooks"]["UserPromptSubmit"][0]                     # o hook da pessoa continua, intacto
    ours = [h for g in ups for h in g["hooks"] if "--codex" in h["command"]]
    assert len(ours) == 1 and ours[0]["type"] == "command" and ours[0]["timeout"] == 10 and ours[0]["commandWindows"] == ours[0]["command"]
    assert set(once["hooks"]) == {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
    assert once["hooks"]["PreToolUse"][0]["matcher"] == "*" and "matcher" not in ups[-1]   # matcher é ignorado no UserPromptSubmit
    assert setup.remove_ours(once)["hooks"] == mine["hooks"]                  # remover deixa só o que era da pessoa


def test_deploy_user_installs_and_removes_codex_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(deploy, "enroll", lambda *a, **k: {"api_key": "ps_k"})
    monkeypatch.setattr(deploy.client, "get_hook_config", lambda cfg: {"failure_mode": "open"})
    monkeypatch.setattr(deploy.setup.Path, "home", classmethod(lambda cls: tmp_path))
    out = []
    rc = deploy.install("http://s", "pse_t", ["codex_cli"], None, "open", None, False, say=out.append, user=True)
    f = tmp_path / ".codex" / "hooks.json"
    assert rc == 0 and f.is_file() and "/hooks" in "\n".join(out)             # avisa que a pessoa precisa confiar nos hooks
    assert "--codex" in f.read_text()
    deploy.uninstall(None, say=out.append, user=True)
    assert json.loads(f.read_text()).get("hooks", {}) == {}


def test_codex_events_are_labelled_codex_cli_and_experimental():
    from promptshield_claude_hook import cli, config
    cfg = config.Config(api_url="http://x", api_key="k")
    sent = []
    import promptshield_claude_hook.client as c
    orig = c.post_event
    c.post_event = lambda cfg_, ev: sent.append(ev) or {"decision": "allow"}
    try:
        cli.run_hook(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "SIMULADO: oi"}), cfg, "codex_cli")
    finally:
        c.post_event = orig
    assert sent[0]["source"]["app"] == "codex_cli" and sent[0]["source"]["integration_status"] == "experimental"
