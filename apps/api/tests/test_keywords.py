"""Palavras-chave monitoradas: alerta em todo prompt com a palavra e pontuação opcional. Dados SINTÉTICOS (simulados)."""
import pytest
from conftest import event

from app.keywords.matcher import Rule, effective_score, find

pytestmark_db = pytest.mark.db


def test_matcher_ignores_case_and_accents():
    assert find("Documento CONFIDENCIAL do projeto", [Rule("1", "confidencial")])
    assert find("projeto Ação Fênix", [Rule("1", "acao fenix")])
    assert not find("nada aqui", [Rule("1", "fenix")])


def test_matcher_whole_word():
    assert not find("reaproveitar", [Rule("1", "proveit", whole_word=True)])
    assert find("projeto fenix, ok", [Rule("1", "fenix", whole_word=True)])


def test_effective_score_keeps_calculated_unless_chosen():
    assert effective_score(12, [Rule("1", "x")]) == 12
    assert effective_score(12, [Rule("1", "x", score=80), Rule("2", "y", score=60)]) == 80
    assert effective_score(90, [Rule("1", "x", score=40)]) == 40


def _add(client, world, **body):
    r = client.post("/v1/keywords", json={"term": "projeto fenix", **body}, headers=world.user("admin"))
    assert r.status_code == 201, r.text
    return r.json()


def _send(client, world, text):
    r = client.post("/v1/events", json=event(text), headers=world.key())
    assert r.status_code == 200, r.text
    return r.json()


def _alerts(client, world):
    return client.get("/v1/alerts?rule=palavra_chave", headers=world.user("admin")).json()


@pytest.mark.db
def test_every_prompt_with_the_word_alerts_and_score_stays_calculated(client, world):
    _add(client, world)
    base = _send(client, world, "resuma a ata sem a palavra")["risk"]["score"]
    r1 = _send(client, world, "Resuma o PROJETO Fênix para a diretoria (simulado)")
    _send(client, world, "outro pedido sobre o projeto fenix (simulado)")
    _send(client, world, "texto sem relação (simulado)")
    assert len(_alerts(client, world)) == 2                      # um alerta por prompt, não por usuário/dia
    assert r1["risk"]["score"] == base                           # sem pontuação escolhida: continua a do motor
    assert not any("definida pelo administrador" in x["rule"] for x in r1["risk"]["reasons"])


@pytest.mark.db
def test_chosen_score_replaces_calculated_and_is_explained(client, world):
    _add(client, world, score=85)
    r = _send(client, world, "fale do projeto fenix (simulado)")
    assert r["risk"]["score"] == 85
    assert any("definida pelo administrador" in x["rule"] for x in r["risk"]["reasons"])
    a = _alerts(client, world)
    assert a[0]["severity"] == "critico"
    assert r["incident_id"] is not None                          # 85 está na faixa de incidente


@pytest.mark.db
def test_disabled_keyword_does_not_alert_and_roles_and_isolation(client, world):
    k = _add(client, world)
    assert client.post("/v1/keywords", json={"term": "x1"}, headers=world.user("analista")).status_code == 403
    assert client.get("/v1/keywords", headers=world.user("analista")).status_code == 200
    assert client.post("/v1/keywords", json={"term": "projeto fenix"}, headers=world.user("admin")).status_code == 409
    assert client.post("/v1/keywords", json={"term": "projeto fenix", "score": 101}, headers=world.user("admin")).status_code == 422
    r = client.put(f"/v1/keywords/{k['id']}", json={"term": "projeto fenix", "enabled": False}, headers=world.user("admin"))
    assert r.status_code == 200
    _send(client, world, "projeto fenix (simulado)")
    assert _alerts(client, world) == []
    assert client.get("/v1/keywords", headers=world.user("admin", tenant="b")).json() == []
    assert client.delete(f"/v1/keywords/{k['id']}", headers=world.user("admin")).status_code == 204
