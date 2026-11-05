"""Painel de sensores: IAs escolhidas por máquina, atualização pelo próprio sensor e evidência (eventos) por IA. Dados SINTÉTICOS."""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import event

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    from app import ratelimit
    ratelimit.reset()


def token(client, world, who="admin"):
    return client.post("/v1/enrollment-tokens", json={"name": "piloto"}, headers=world.user(who)).json()["token"]


def enroll(client, tok, host, ias=(), tools=("claude_code",)):
    r = client.post("/v1/enroll", json={"token": tok, "hostname": host, "os": "windows", "client_version": "0.1", "tools": list(tools), "ias": list(ias)})
    assert r.status_code == 201, r.text
    return r.json()["api_key"]


def send(client, key, app, when=None, text="SIMULADO: oi", user=None):
    ev = event(text, source={"channel": "browser" if app.endswith("_web") else "agent_hook", "app": app, "integration_status": "experimental"})
    if when:
        ev["occurred_at"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    if user:
        ev["actor"] = {"user_id": user, "department": "Engenharia"}
    r = client.post("/v1/events", json=ev, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text


def devices(client, world, who="leitura"):
    return {d["hostname"]: d for d in client.get("/v1/devices", headers=world.user(who)).json()["devices"]}


def test_enrollment_stores_chosen_ias_and_validates_them(client, world):
    tok = token(client, world)
    enroll(client, tok, "NB-ANA", ias=["gemini_web", "chatgpt_web", "chatgpt_web", "claude_code"], tools=["claude_code", "browser_extension"])
    out = client.get("/v1/devices", headers=world.user("leitura")).json()
    d = out["devices"][0]
    assert d["hostname"] == "NB-ANA" and d["ias"] == ["chatgpt_web", "claude_code", "gemini_web"]          # ordenado, sem repetir
    assert out["ias_coverage"] == {"chatgpt_web": 1, "claude_code": 1, "gemini_web": 1}
    for bad in (["ChatGPT"], ["a"], ["x" * 41], ["com espaço"], [f"ia_{i}" for i in range(21)]):
        r = client.post("/v1/enroll", json={"token": tok, "hostname": "NB-X", "os": "windows", "tools": [], "ias": bad})
        assert r.status_code == 422, bad
    assert devices(client, world)["NB-ANA"]["ias"]                                                         # a recusa não gastou nem criou nada
    assert len(devices(client, world)) == 1


def test_a_sensor_can_report_its_ias_later_and_choices_accumulate_with_add(client, world):
    key = enroll(client, token(client, world), "NB-BIA")
    assert devices(client, world)["NB-BIA"]["ias"] == []
    h = {"X-API-Key": key}
    assert client.put("/v1/device/ias", json={"ias": ["claude_code"], "mode": "add"}, headers=h).json() == {"ias": ["claude_code"]}
    assert client.put("/v1/device/ias", json={"ias": ["gemini_web"], "mode": "add"}, headers=h).json() == {"ias": ["claude_code", "gemini_web"]}
    assert client.put("/v1/device/ias", json={"ias": ["claude_web"]}, headers=h).json() == {"ias": ["claude_web"]}      # padrão: substitui
    assert devices(client, world)["NB-BIA"]["ias"] == ["claude_web"]
    assert client.put("/v1/device/ias", json={"ias": ["Maiúscula"]}, headers=h).status_code == 422
    assert client.put("/v1/device/ias", json={"ias": [], "extra": 1}, headers=h).status_code == 422
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'device.ias_update'").scalar() == 3


def test_only_a_device_key_can_report_and_nobody_else(client, world):
    assert client.put("/v1/device/ias", json={"ias": ["claude_code"]}, headers=world.key()).status_code == 404        # chave padrão do tenant não é máquina
    assert client.put("/v1/device/ias", json={"ias": ["claude_code"]}, headers=world.user("admin")).status_code == 403  # usuário do console não
    assert client.put("/v1/device/ias", json={"ias": ["claude_code"]}).status_code in (401, 403)
    key = enroll(client, token(client, world), "NB-CAIO")
    d = client.get("/v1/devices", headers=world.user("admin")).json()["devices"][0]
    client.post(f"/v1/devices/{d['id']}/revoke", headers=world.user("admin"))
    assert client.put("/v1/device/ias", json={"ias": ["claude_code"]}, headers={"X-API-Key": key}).status_code == 401  # chave revogada


def test_activity_per_sensor_and_app_is_real_evidence_and_not_mixed_between_sensors(client, world):
    now = datetime.now(timezone.utc)
    a = enroll(client, token(client, world), "NB-A", ias=["chatgpt_web", "claude_code"])
    b = enroll(client, token(client, world), "NB-B", ias=["chatgpt_web"])
    send(client, a, "chatgpt_web")
    send(client, a, "chatgpt_web")
    send(client, a, "claude_code", when=now - timedelta(days=10))               # fora dos 7 dias, dentro dos 30
    send(client, a, "gemini_web", when=now - timedelta(days=40))                # fora dos 30: não aparece
    send(client, b, "claude_code")
    assert client.post("/v1/events", json=event("SIMULADO: chave padrão do tenant"), headers=world.key()).status_code == 200   # sem sensor
    d = devices(client, world)
    act_a, act_b = d["NB-A"]["activity"], d["NB-B"]["activity"]
    assert act_a["chatgpt_web"]["events_7d"] == 2 and act_a["chatgpt_web"]["events_30d"] == 2 and act_a["chatgpt_web"]["last_at"]
    assert act_a["claude_code"]["events_7d"] == 0 and act_a["claude_code"]["events_30d"] == 1
    assert "gemini_web" not in act_a
    assert set(act_b) == {"claude_code"} and act_b["claude_code"]["events_7d"] == 1                        # o evento do B não vai para o A
    # o evento da chave padrão do tenant tem chave, mas nenhuma máquina: não aparece em sensor nenhum
    assert world.sql("SELECT count(*) FROM events e WHERE NOT EXISTS (SELECT 1 FROM devices d WHERE d.api_key_id = e.api_key_id)").scalar() == 1


def test_last_user_and_how_many_people_used_each_machine(client, world):
    now = datetime.now(timezone.utc)
    a = enroll(client, token(client, world), "NB-COMPARTILHADO")
    b = enroll(client, token(client, world), "NB-SOZINHO")
    enroll(client, token(client, world), "NB-VAZIO")
    send(client, a, "claude_code", when=now - timedelta(hours=5), user="ana@x.example")
    send(client, a, "claude_code", when=now - timedelta(hours=2), user="bruno@x.example")
    send(client, a, "claude_code", when=now - timedelta(hours=1), user="bruno@x.example")
    send(client, a, "claude_code", when=now - timedelta(days=45), user="velho@x.example")           # fora dos 30 dias: não conta
    send(client, b, "chatgpt_web", user="carla@x.example")
    d = devices(client, world)
    assert d["NB-COMPARTILHADO"]["last_user"] == "bruno@x.example" and d["NB-COMPARTILHADO"]["users_30d"] == 2
    assert d["NB-COMPARTILHADO"]["last_department"] == "Engenharia" and d["NB-COMPARTILHADO"]["last_user_at"]
    assert d["NB-SOZINHO"]["last_user"] == "carla@x.example" and d["NB-SOZINHO"]["users_30d"] == 1
    assert d["NB-VAZIO"]["last_user"] is None and d["NB-VAZIO"]["users_30d"] == 0


def test_events_can_be_filtered_by_sensor_and_do_not_leak_across_tenants(client, world):
    a = enroll(client, token(client, world), "NB-A")
    b = enroll(client, token(client, world), "NB-B")
    send(client, a, "chatgpt_web", text="SIMULADO: do sensor A")
    send(client, b, "chatgpt_web", text="SIMULADO: do sensor B 1")
    send(client, b, "claude_code", text="SIMULADO: do sensor B 2")
    ids = {h: d["id"] for h, d in devices(client, world).items()}
    rows = lambda sensor: client.get("/v1/events", params={"days": 30, "sensor": sensor}, headers=world.user("leitura"))   # noqa: E731
    got_b = rows(ids["NB-B"]).json()
    assert len(got_b) == 2 and all("sensor B" in r["masked_text"] for r in got_b) and rows(ids["NB-B"]).headers["x-total-count"] == "2"
    assert [r["masked_text"] for r in rows(ids["NB-A"]).json()] == ["SIMULADO: do sensor A"]
    assert rows("00000000-0000-4000-8000-000000000000").json() == []                       # sensor inexistente: nada
    assert client.get("/v1/events", params={"sensor": "nao-e-uuid"}, headers=world.user("leitura")).status_code == 422
    # sensor de OUTRA empresa: a RLS impede de ver o dispositivo e, portanto, de ver evento
    other_tok = token(client, world, who="admin")
    assert other_tok
    from conftest import event as ev_
    other_key = world.key("b")
    client.post("/v1/events", json=ev_("SIMULADO: tenant B"), headers=other_key)
    assert client.get("/v1/events", params={"days": 30, "sensor": ids["NB-A"]}, headers=world.user("admin", "b")).json() == []


def test_sensors_csv_roles_filters_audit_and_formula_guard(client, world):
    now = datetime.now(timezone.utc)
    a = enroll(client, token(client, world), "=cmd|' /c calc'!A1", ias=["chatgpt_web", "claude_code", "codex_cli"], tools=["claude_code", "browser_extension"])
    enroll(client, token(client, world), "NB-DOIS", ias=["gemini_web"])
    send(client, a, "chatgpt_web", when=now - timedelta(hours=1), user="=HYPERLINK(\"http://evil\")")
    for role in ("leitura", "analista"):
        assert client.get("/v1/devices/export.csv", headers=world.user(role)).status_code == 403
    assert client.get("/v1/devices/export.csv", headers=world.key()).status_code in (401, 403)
    r = client.get("/v1/devices/export.csv", headers=world.user("auditor"))
    assert r.status_code == 200 and r.text.startswith("\ufeffmaquina,sistema,versao_sensor,situacao")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.lstrip("\ufeff").splitlines()
    assert len(lines) == 3
    assert "'=cmd" in r.text and "'=HYPERLINK" in r.text                                    # fórmula de planilha neutralizada, no nome da máquina e no usuário
    row = next(x for x in lines if "NB-DOIS" in x)
    assert "gemini_web" in row and ",nunca," in row                                       # habilitada, nunca enviou
    only = client.get("/v1/devices/export.csv", params={"ia": "gemini_web"}, headers=world.user("admin")).text
    assert "NB-DOIS" in only and "cmd" not in only
    assert "NB-DOIS" not in client.get("/v1/devices/export.csv", params={"q": "cmd"}, headers=world.user("admin")).text
    assert client.get("/v1/devices/export.csv", params={"situacao": "ativo"}, headers=world.user("admin")).text.count("\n") == 2   # cabeçalho + a máquina que enviou
    assert client.get("/v1/devices/export.csv", params={"situacao": "inventado"}, headers=world.user("admin")).status_code == 422
    first = next(x for x in lines if "cmd" in x)
    assert ",chatgpt_web;claude_code;codex_cli," in first and ",chatgpt_web;claude_code," not in first.replace(",chatgpt_web;claude_code;codex_cli,", "")   # capturando: só a que tem evento (chatgpt_web)
    assert world.sql("SELECT count(*) FROM audit_log WHERE action = 'export.sensors_csv'").scalar() == 4   # só as exportações que deram certo (a de filtro inválido deu 422)
