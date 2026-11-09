"""Fila de incidentes: status em lista (pendentes), triagem rápida e palavra-chave. Dados SINTÉTICOS."""
import pytest
from conftest import event

pytestmark = pytest.mark.db
SECRET = "AKIAZ7QW4XK2M9PLR3TN"


def _send(client, world, text):
    r = client.post("/v1/events", json=event(text), headers=world.key())
    assert r.status_code == 200, r.text
    return r.json()


def test_pending_filter_triage_and_keyword_in_the_queue(client, world):
    adm, ana, ro = world.user("admin"), world.user("analista"), world.user("leitura")
    client.post("/v1/keywords", json={"term": "jeje", "score": 88}, headers=adm)
    a = _send(client, world, f"SIMULADO: chave {SECRET} para o deploy")["incident_id"]
    b = _send(client, world, "SIMULADO: jeje ontem")["incident_id"]
    assert a and b
    ids = lambda q: {i["id"] for i in client.get(f"/v1/incidents{q}", headers=ro).json()}   # noqa: E731
    assert ids("?status=aberto,em analise") == {a, b} == ids("")
    row = next(i for i in client.get("/v1/incidents", headers=ro).json() if i["id"] == b)
    assert row["keyword_hits"] == ["jeje"] and row["risk_score"] == 88

    assert client.patch(f"/v1/incidents/{a}", json={"status": "em analise"}, headers=ro).status_code == 403
    assert client.patch(f"/v1/incidents/{a}", json={"status": "em analise"}, headers=ana).json()["status"] == "em analise"
    assert client.patch(f"/v1/incidents/{b}", json={"status": "resolvido"}, headers=ana).status_code == 200
    assert ids("?status=aberto,em analise") == {a}                      # o resolvido sai da vista padrão
    assert ids("?status=resolvido") == {b} and ids("?status=resolvido,aberto,em analise,falso positivo") == {a, b}
    assert ids("") == {a, b}                                           # sem filtro: tudo, nada some do registro
    assert client.patch(f"/v1/incidents/{b}", json={"status": "aberto"}, headers=ana).status_code == 200      # desfazer
    assert ids("?status=aberto,em analise") == {a, b}
    assert client.get("/v1/incidents?status=arquivado", headers=ro).status_code == 422
    assert client.get("/v1/incidents?status=aberto,xx", headers=ro).status_code == 422
    log = world.sql("SELECT count(*) FROM audit_log WHERE action = 'incident.update'").scalar()
    assert log == 3                                                    # as 3 mudanças válidas ficam na auditoria; a recusada (leitura) não muda nada
