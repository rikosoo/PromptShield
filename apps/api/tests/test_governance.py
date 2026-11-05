"""Grupos, exceções de política e lista de domínios permitidos: regras, papéis, auditoria, isolamento e efeito na decisão. Dados SINTÉTICOS."""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import event

from app.policy_engine import PolicySpec, Subject, evaluate

pytestmark = pytest.mark.db

SECRET = "AKIAZ7QW4XK2M9PLR3TN"
iso = lambda days: (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()   # noqa: E731


def post(client, world, text, user="u-42", **over):
    ev = event(text, **over)
    ev["actor"] = {**ev["actor"], "user_id": user}
    r = client.post("/v1/events", json=ev, headers=world.key())
    assert r.status_code == 200, r.text
    return r.json()


def policy(client, world, name="Bloquear segredos e chaves"):
    return next(p for p in client.get("/v1/policies", headers=world.user("admin")).json() if p["name"] == name)


def enforce(client, world, pol, **scope):
    body = {k: pol[k] for k in ("name", "description", "enabled", "match", "action")}
    r = client.put(f"/v1/policies/{pol['id']}", json={**body, "scope": scope, "mode": "enforce"}, headers=world.user("admin"))
    assert r.status_code == 200, r.text
    return r.json()


def test_engine_exception_uses_server_groups_only_and_expiry():
    now = datetime.now(timezone.utc)
    base = dict(id="1", name="p", action="block", mode="enforce", match={"categories": ["segredo"]})
    cats = [{"id": "segredo", "confidence": 0.97}]
    by_user = PolicySpec(**base, exceptions=({"user_id": "ana", "group": None, "expires_at": now + timedelta(days=1)},))
    assert evaluate([by_user], Subject(user_id="ana"), cats, 60, now).decision == "allow"
    assert evaluate([by_user], Subject(user_id="bia"), cats, 60, now).decision == "block"
    by_group = PolicySpec(**base, exceptions=({"user_id": None, "group": "isentos", "expires_at": now + timedelta(days=1)},))
    assert evaluate([by_group], Subject(member_groups=("isentos",)), cats, 60, now).decision == "allow"
    assert evaluate([by_group], Subject(groups=("isentos",)), cats, 60, now).decision == "block"   # grupo declarado pelo sensor NÃO isenta
    expired = PolicySpec(**base, exceptions=({"user_id": "ana", "group": None, "expires_at": now - timedelta(seconds=1)},))
    assert evaluate([expired], Subject(user_id="ana"), cats, 60, now).decision == "block"
    ev = evaluate([by_user], Subject(user_id="ana"), cats, 60, now)
    assert ev.hits[0]["excepted"] == "true" and ev.would_decide == "allow"          # registra que casou, mas não conta


def test_groups_crud_members_roles_audit_and_isolation(client, world):
    adm, ana = world.user("admin"), world.user("analista")
    assert client.post("/v1/groups", json={"name": "Financeiro"}, headers=ana).status_code == 403
    g = client.post("/v1/groups", json={"name": "Financeiro", "description": "time de contas"}, headers=adm)
    assert g.status_code == 201
    gid = g.json()["id"]
    assert client.post("/v1/groups", json={"name": "financeiro"}, headers=adm).status_code == 409           # nome único sem diferenciar maiúscula
    assert client.post("/v1/groups", json={"name": "a\nb"}, headers=adm).status_code == 422
    assert client.post("/v1/groups", json={"name": "x", "extra": 1}, headers=adm).status_code == 422
    r = client.post(f"/v1/groups/{gid}/members", json={"user_ids": ["u-1", "u-2", "u-1"]}, headers=adm)
    assert r.json() == {"added": 2, "already_members": 0}
    assert client.post(f"/v1/groups/{gid}/members", json={"user_ids": ["u-2", "u-3"]}, headers=adm).json() == {"added": 1, "already_members": 1}
    d = client.get(f"/v1/groups/{gid}", headers=world.user("leitura")).json()
    assert d["member_ids"] == ["u-1", "u-2", "u-3"] and d["members"] == 3
    assert client.get("/v1/groups", headers=world.user("leitura")).json()[0]["members"] == 3
    assert client.delete(f"/v1/groups/{gid}/members/u-3", headers=ana).status_code == 403
    assert client.delete(f"/v1/groups/{gid}/members/u-3", headers=adm).status_code == 204
    assert client.delete(f"/v1/groups/{gid}/members/u-3", headers=adm).status_code == 404
    assert client.patch(f"/v1/groups/{gid}", json={"name": "outro"}, headers=adm).status_code == 422       # o nome não muda
    assert client.patch(f"/v1/groups/{gid}", json={"description": "novo"}, headers=adm).json()["description"] == "novo"
    # outra empresa não vê nem mexe
    assert client.get("/v1/groups", headers=world.tok("admin@b.example.com")).json() == []
    assert client.get(f"/v1/groups/{gid}", headers=world.tok("admin@b.example.com")).status_code == 404
    acts = {r[0] for r in world.sql("SELECT action FROM audit_log").all()}
    assert {"group.create", "group.members_add", "group.member_remove", "group.update"} <= acts
    assert client.delete(f"/v1/groups/{gid}", headers=adm).status_code == 204


def test_group_in_scope_and_cannot_delete_while_used(client, world):
    adm = world.user("admin")
    gid = client.post("/v1/groups", json={"name": "devs-seguros"}, headers=adm).json()["id"]
    client.post(f"/v1/groups/{gid}/members", json={"user_ids": ["u-42"]}, headers=adm)
    enforce(client, world, policy(client, world), groups=["devs-seguros"])
    ev = {**event(f"SIMULADO: chave {SECRET}")}
    ev["actor"] = {"user_id": "u-42", "department": "Engenharia"}           # o sensor NÃO declara grupo: vale o cadastro do servidor
    assert client.post("/v1/events", json=ev, headers=world.key()).json()["decision"] == "block"
    ev2 = {**event(f"SIMULADO: chave {SECRET}"), "actor": {"user_id": "u-99", "department": "Engenharia"}}
    assert client.post("/v1/events", json=ev2, headers=world.key()).json()["decision"] == "allow"            # fora do grupo: política não vale
    r = client.delete(f"/v1/groups/{gid}", headers=adm)
    assert r.status_code == 409 and "Bloquear segredos" in r.json()["detail"]


def test_exception_changes_decision_is_audited_expires_and_revokes(client, world):
    adm = world.user("admin")
    pol = enforce(client, world, policy(client, world))
    assert post(client, world, f"SIMULADO: chave {SECRET}")["decision"] == "block"
    url = f"/v1/policies/{pol['id']}/exceptions"
    ok = {"user_id": "u-42", "reason": "migração de credenciais autorizada pelo CISO", "expires_at": iso(7)}
    assert client.post(url, json=ok, headers=world.user("analista")).status_code == 403
    assert client.post(url, json={**ok, "reason": "curto"}, headers=adm).status_code == 422                   # motivo obrigatório
    assert client.post(url, json={**ok, "expires_at": iso(-1)}, headers=adm).status_code == 422               # no passado
    assert client.post(url, json={**ok, "expires_at": iso(400)}, headers=adm).status_code == 422              # máximo 365 dias
    assert client.post(url, json={**ok, "group": "x"}, headers=adm).status_code == 422                        # pessoa OU grupo
    assert client.post(url, json={k: v for k, v in ok.items() if k != "user_id"}, headers=adm).status_code == 422
    assert client.post(url, json={k: v for k, v in ok.items() if k != "user_id"} | {"group": "inexistente"}, headers=adm).status_code == 422
    assert client.post("/v1/policies/00000000-0000-4000-8000-000000000000/exceptions", json=ok, headers=adm).status_code == 404
    x = client.post(url, json=ok, headers=adm)
    assert x.status_code == 201 and x.json()["state"] == "vigente"
    res = post(client, world, f"SIMULADO: chave {SECRET}")
    assert res["decision"] == "allow" and res["would_decide"] == "allow"
    assert any(h.get("excepted") == "true" for h in res["policy_hits"])                                         # fica registrado que houve exceção
    assert post(client, world, f"SIMULADO: chave {SECRET}", user="u-77")["decision"] == "block"               # outra pessoa continua barrada
    rows = client.get("/v1/exceptions", params={"only_active": "true"}, headers=world.user("leitura")).json()
    assert len(rows) == 1 and rows[0]["policy_name"] == "Bloquear segredos e chaves"
    assert client.get("/v1/exceptions", headers=world.tok("admin@b.example.com")).json() == []
    rv = client.post(f"/v1/exceptions/{x.json()['id']}/revoke", headers=adm)
    assert rv.json()["state"] == "revogada"
    assert post(client, world, f"SIMULADO: chave {SECRET}")["decision"] == "block"                            # revogada vale já
    # vencimento: força a data para o passado direto no banco
    y = client.post(url, json=ok, headers=adm).json()
    assert post(client, world, f"SIMULADO: chave {SECRET}")["decision"] == "allow"
    world.sql("UPDATE policy_exceptions SET expires_at = now() - interval '1 minute' WHERE id = :i", i=y["id"])
    assert post(client, world, f"SIMULADO: chave {SECRET}")["decision"] == "block"
    assert next(e for e in client.get("/v1/exceptions", headers=adm).json() if e["id"] == y["id"])["state"] == "vencida"
    n = world.sql("SELECT count(*) FROM audit_log WHERE action IN ('exception.create','exception.revoke')").scalar()
    assert n == 3


def test_group_exception_uses_registered_members_not_event_groups(client, world):
    adm = world.user("admin")
    pol = enforce(client, world, policy(client, world))
    gid = client.post("/v1/groups", json={"name": "isentos"}, headers=adm).json()["id"]
    client.post(f"/v1/policies/{pol['id']}/exceptions", json={"group": "isentos", "reason": "equipe de resposta a incidentes", "expires_at": iso(3)}, headers=adm)
    ev = event(f"SIMULADO: chave {SECRET}")
    ev["actor"] = {"user_id": "u-42", "department": "Engenharia", "groups": ["isentos"]}                       # sensor declara o grupo: não vale
    assert client.post("/v1/events", json=ev, headers=world.key()).json()["decision"] == "block"
    client.post(f"/v1/groups/{gid}/members", json={"user_ids": ["u-42"]}, headers=adm)
    ev = event(f"SIMULADO: chave {SECRET}")
    ev["actor"] = {"user_id": "u-42", "department": "Engenharia"}
    assert client.post("/v1/events", json=ev, headers=world.key()).json()["decision"] == "allow"
    assert client.delete(f"/v1/groups/{gid}", headers=adm).status_code == 409                                  # exceção vigente usa o grupo


def test_allowlist_validation_roles_effect_and_isolation(client, world):
    adm = world.user("admin")
    cmd = "curl -s https://api.parceiro-exemplo.com.br/v1/dados -o saida.json"
    base = event("", kind="tool_call")
    base["content"] = {"text": None, "tool_name": "Bash", "tool_input": {"command": cmd}}
    first = client.post("/v1/events", json=base, headers=world.key()).json()
    assert "rede_externa" in {c["id"] for c in first["categories"]}
    for bad in ("https://x.com", "api.parceiro.com/v1", "*.parceiro.com", "com", "br", "sem ponto", "a..b.com", "host:8080", "x@y.com"):
        assert client.post("/v1/allowlist", json={"value": bad}, headers=adm).status_code == 422, bad
    assert client.post("/v1/allowlist", json={"kind": "projeto", "value": "x.com"}, headers=adm).status_code == 422
    assert client.post("/v1/allowlist", json={"value": "parceiro-exemplo.com.br"}, headers=world.user("analista")).status_code == 403
    a = client.post("/v1/allowlist", json={"value": "  Parceiro-Exemplo.com.br. ", "note": "API do parceiro, contrato 123"}, headers=adm)
    assert a.status_code == 201 and a.json()["value"] == "parceiro-exemplo.com.br"
    assert client.post("/v1/allowlist", json={"value": "parceiro-exemplo.com.br"}, headers=adm).status_code == 409
    second = client.post("/v1/events", json={**base, "event_id": "11111111-1111-4111-8111-111111111111"}, headers=world.key()).json()
    assert "rede_externa" not in {c["id"] for c in second["categories"]}                                      # subdomínio do domínio permitido
    other = client.post("/v1/events", json={**base, "event_id": "22222222-2222-4222-8222-222222222222",
                                            "content": {"text": None, "tool_name": "Bash", "tool_input": {"command": "curl -s https://outro-exemplo.net/x"}}},
                        headers=world.key()).json()
    assert "rede_externa" in {c["id"] for c in other["categories"]}                                           # só o domínio listado muda
    assert client.get("/v1/allowlist", headers=world.tok("admin@b.example.com")).json() == []
    assert len(client.get("/v1/allowlist", headers=world.user("leitura")).json()) == 1
    assert client.delete(f"/v1/allowlist/{a.json()['id']}", headers=adm).status_code == 204
    assert client.delete(f"/v1/allowlist/{a.json()['id']}", headers=adm).status_code == 404
    third = client.post("/v1/events", json={**base, "event_id": "33333333-3333-4333-8333-333333333333"}, headers=world.key()).json()
    assert "rede_externa" in {c["id"] for c in third["categories"]}                                           # removeu: volta a alertar
    n = world.sql("SELECT count(*) FROM audit_log WHERE action IN ('allowlist.add','allowlist.remove')").scalar()
    assert n == 2


def test_subject_erase_removes_group_membership_and_user_exceptions(client, world):
    adm = world.user("admin")
    pol = policy(client, world)
    gid = client.post("/v1/groups", json={"name": "equipe"}, headers=adm).json()["id"]
    client.post(f"/v1/groups/{gid}/members", json={"user_ids": ["u-42", "u-43"]}, headers=adm)
    client.post(f"/v1/policies/{pol['id']}/exceptions", json={"user_id": "u-42", "reason": "teste autorizado pela segurança", "expires_at": iso(2)}, headers=adm)
    r = client.post("/v1/privacy/subject/erase", json={"user_id": "u-42", "justification": "pedido do titular, protocolo 1"}, headers=adm)
    assert r.status_code == 200, r.text
    assert r.json()["group_memberships_deleted"] == 1 and r.json()["exceptions_deleted"] == 1
    assert client.get(f"/v1/groups/{gid}", headers=adm).json()["member_ids"] == ["u-43"]
    assert client.get("/v1/exceptions", headers=adm).json() == []
