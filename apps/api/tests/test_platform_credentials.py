"""O token do próprio PromptShield colado num prompt não pode ficar no texto guardado. Valores SINTÉTICOS."""
import pytest
from conftest import event

pytestmark = pytest.mark.db

ENROLL = "pse_0f9e8d7c_Qm3vK8xT2LzR7yWc9HnB4dJf6sAe1UgP"
KEY = "ps_a1b2c3d4_Zk3Qm9Xv7LpR2sT8wYhN5cJe0UfGdB1A"


def test_own_credentials_are_masked_in_stored_text_and_response(client, world):
    ev = event(f"SIMULADO: $env:PS_TOKEN='{ENROLL}' e a chave {KEY}")
    r = client.post("/v1/events", json=ev, headers=world.key())
    assert r.status_code == 200, r.text
    body = r.json()
    assert ENROLL not in str(body) and KEY not in str(body)
    assert "ps_****" in body["masked_text"] and "pse_****" in body["masked_text"]
    assert any(c["id"] == "segredo" for c in body["categories"]) and body["risk"]["score_version"] == "2026-11-d"
    stored = client.get(f"/v1/events/{ev['event_id']}", headers=world.user("leitura")).text
    assert ENROLL not in stored and KEY not in stored
    assert world.sql("SELECT count(*) FROM events WHERE masked_text LIKE '%0f9e8d7c%' OR masked_text LIKE '%a1b2c3d4%'").scalar() == 0
