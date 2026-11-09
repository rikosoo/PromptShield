"""Colaboradores (usuários do console): lista, criação com função e departamento, edição, desativação e proteções. Dados SINTÉTICOS."""
import pytest

pytestmark = pytest.mark.db


def _create(client, world, **over):
    body = {"email": "nova.pessoa@a.example.com", "display_name": "Nova Pessoa", "role": "analista", "department": "Segurança", **over}
    return client.post("/v1/users", json=body, headers=world.user("admin"))


def test_list_create_edit_and_roles(client, world):
    adm = world.user("admin")
    rows = client.get("/v1/users", headers=adm).json()
    me = next(r for r in rows if r["is_me"])
    assert me["role"] == "admin" and {"display_name", "created_at", "active", "department"} <= set(me)
    r = _create(client, world)
    assert r.status_code == 201 and r.json()["role"] == "analista" and r.json()["active"] is True
    uid = r.json()["id"]
    # papéis: só administrador mexe
    for who in ("analista", "auditor", "leitura"):
        assert client.get("/v1/users", headers=world.user(who)).status_code == 403
        assert client.patch(f"/v1/users/{uid}", json={"role": "admin"}, headers=world.user(who)).status_code == 403
        assert _create_as(client, world, who).status_code == 403
    # validações
    assert _create(client, world, email="sem-arroba").status_code == 422
    assert _create(client, world, email="a b@x.example").status_code == 422
    assert _create(client, world, email="NOVA.PESSOA@A.EXAMPLE.COM").status_code == 409          # e-mail igual, só muda a caixa
    assert _create(client, world, email="x@y.example", role="chefe").status_code == 422
    assert client.patch(f"/v1/users/{uid}", json={}, headers=adm).status_code == 422
    assert client.patch(f"/v1/users/{uid}", json={"email": "outro@x.example"}, headers=adm).status_code == 422     # e-mail não muda
    # editar
    p = client.patch(f"/v1/users/{uid}", json={"role": "auditor", "department": "Compliance", "display_name": "Nova P."}, headers=adm)
    assert p.status_code == 200 and (p.json()["role"], p.json()["department"], p.json()["display_name"]) == ("auditor", "Compliance", "Nova P.")
    # a auditoria guarda antes e depois, sem e-mail
    row = world.sql("SELECT detail::text FROM audit_log WHERE action = 'user.update'").scalar()
    assert '"auditor"' in row and "analista" in row and "nova.pessoa" not in row


def _create_as(client, world, who):
    return client.post("/v1/users", json={"email": "z@z.example", "role": "leitura"}, headers=world.user(who))


def test_deactivated_collaborator_loses_access_and_can_come_back(client, world):
    adm = world.user("admin")
    leitura = world.user("leitura")
    assert client.get("/v1/me", headers=leitura).status_code == 200
    uid = next(r["id"] for r in client.get("/v1/users", headers=adm).json() if r["email"].startswith("leitura@"))
    assert client.patch(f"/v1/users/{uid}", json={"active": False}, headers=adm).status_code == 200
    assert client.get("/v1/me", headers=leitura).status_code == 401                          # inativo: não entra
    assert client.patch(f"/v1/users/{uid}", json={"active": True}, headers=adm).status_code == 200
    assert client.get("/v1/me", headers=leitura).status_code == 200


def test_last_admin_and_self_protections(client, world):
    adm = world.user("admin")
    me = next(r for r in client.get("/v1/users", headers=adm).json() if r["is_me"])
    # sozinho como administrador: não rebaixa, não desativa, não remove
    for body in ({"role": "analista"}, {"active": False}):
        assert client.patch(f"/v1/users/{me['id']}", json=body, headers=adm).status_code == 409
    assert client.delete(f"/v1/users/{me['id']}", headers=adm).status_code == 409
    # com um segundo administrador, ninguém tira o próprio acesso (outro administrador faz isso), mas o outro pode ser rebaixado
    other = _create(client, world, email="segundo.admin@a.example.com", role="admin").json()["id"]
    assert client.patch(f"/v1/users/{me['id']}", json={"role": "leitura"}, headers=adm).status_code == 409
    assert client.patch(f"/v1/users/{other}", json={"role": "analista"}, headers=adm).status_code == 200
    # voltou a ser o único: segue protegido
    assert client.patch(f"/v1/users/{me['id']}", json={"active": False}, headers=adm).status_code == 409


def test_collaborators_are_isolated_between_companies(client, world):
    emails_a = {r["email"] for r in client.get("/v1/users", headers=world.user("admin")).json()}
    emails_b = {r["email"] for r in client.get("/v1/users", headers=world.user("admin", tenant="b")).json()}
    assert emails_a.isdisjoint(emails_b) and "admin@b.example.com" in emails_b
    uid_a = next(r["id"] for r in client.get("/v1/users", headers=world.user("admin")).json() if r["email"].startswith("leitura@"))
    assert client.patch(f"/v1/users/{uid_a}", json={"role": "admin"}, headers=world.user("admin", tenant="b")).status_code == 404
