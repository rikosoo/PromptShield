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


@pytest.mark.db
def test_keyword_prompt_shows_as_new_alert_in_the_list_even_with_low_score(client, world):
    _add(client, world, term="brocolis")
    r = _send(client, world, "que vontade de comer Brocolis (simulado)")
    assert r["risk"]["score"] == 0 and r["incident_id"] is not None          # score baixo, mas vira alerta "Novo"
    rows = client.get("/v1/events", headers=world.user("admin")).json()
    row = next(x for x in rows if x["event_id"] == r["event_id"])
    assert row["alert_status"] == "novo" and row["flags"]["keyword_hits"] == ["brocolis"] and row["severity"] == "baixo"
    plain = _send(client, world, "texto comum sem a palavra (simulado)")
    assert plain["incident_id"] is None
    assert len(_alerts(client, world)) == 1


# ---------------------------------------------------------------- palavras próximas (aproximada)
from app.keywords.matcher import distance, find_hits, tolerance  # noqa: E402


def test_distance_and_tolerance():
    assert distance("brocolis", "brocoli", 2) == 1 and distance("fenix", "fnei", 3) == 2
    assert distance("fenix", "fneix", 2) == 1                       # letras vizinhas trocadas contam como UMA edição
    assert distance("abc", "abcdefgh", 2) == 3                      # passou do limite: corta
    assert [tolerance(n) for n in (3, 4, 5, 7, 8, 11, 12, 15)] == [0, 0, 1, 1, 2, 2, 3, 3]


@pytest.mark.parametrize("text", ["comprei brocoli hoje", "BRÓCOLIS!", "brocollis", "brocoils no jantar", "brocolos", "brocules", "brocoles",
                                  "superbrocolis", "brocolisxyz", "meubrocolinhos"])
def test_fuzzy_catches_typos_plurals_and_swaps(text):
    hits = find_hits(text, [Rule("1", "brocolis", fuzzy=True)])
    assert len(hits) == 1


def test_fuzzy_marks_approximate_only_when_not_exact():
    exact = find_hits("tem brocolis", [Rule("1", "brocolis", fuzzy=True)])[0]
    near = find_hits("tem brocoli", [Rule("1", "brocolis", fuzzy=True)])[0]
    assert exact.approximate is False and near.approximate is True


def test_fuzzy_off_by_default_and_when_the_rule_says_so():
    assert find("tem brocoli", [Rule("1", "brocolis")]) == []
    assert find("tem brocoli", [Rule("1", "brocolis", fuzzy=False)]) == []


@pytest.mark.parametrize("text", ["comprei couve hoje", "brasil", "os bolsistas", "cpf", "casa", "bronquite", "o procurador", "brasileiro", "rubricas"])
def test_fuzzy_does_not_match_unrelated_words(text):
    assert find(text, [Rule("1", "brocolis", fuzzy=True)]) == []


def test_fuzzy_short_words_stay_exact_and_multiword_terms_work():
    assert find("o cpg foi enviado", [Rule("1", "cpf", fuzzy=True)]) == []           # 3 letras: sem tolerância
    assert find("falei do projeto fenyx", [Rule("1", "projeto fenix", fuzzy=True)])  # cada palavra tolera o seu erro
    assert find("projto fenix", [Rule("1", "projeto fenix", fuzzy=True)])
    assert not find("fenix projeto", [Rule("1", "projeto fenix", fuzzy=True)])       # a ordem importa
    assert not find("projeto sol", [Rule("1", "projeto fenix", fuzzy=True)])


def test_fuzzy_respects_whole_word_for_the_exact_part_only():
    assert find("reaproveitar", [Rule("1", "proveit", whole_word=True, fuzzy=True)]) == []
    assert find("super brocolis", [Rule("1", "brocolis", whole_word=True, fuzzy=True)])


def test_fuzzy_is_fast_on_large_text():
    import time
    text = ("lorem ipsum dolor sit amet consectetur " * 3000) + " brocoli"
    t0 = time.perf_counter()
    assert find(text, [Rule("1", "brocolis", fuzzy=True)])
    assert time.perf_counter() - t0 < 2.0


@pytest.mark.db
def test_api_default_is_fuzzy_and_alert_says_similar_word(client, world):
    k = _add(client, world, term="brocolis")
    assert k["fuzzy"] is True
    r = _send(client, world, "comprei brocoli (simulado)")
    assert r["incident_id"] is not None
    a = _alerts(client, world)
    assert "palavra parecida" in a[0]["title"]          # a API de alertas não expõe `detail`; o título já avisa
    assert world.sql("SELECT detail->>'approximate' FROM alerts WHERE rule = 'palavra_chave'").scalar() == "true"
    exact = _send(client, world, "comprei brocolis (simulado)")
    assert exact["incident_id"] is not None
    off = client.put(f"/v1/keywords/{k['id']}", json={"term": "brocolis", "fuzzy": False}, headers=world.user("admin"))
    assert off.status_code == 200 and off.json()["fuzzy"] is False
    assert _send(client, world, "comprei brocoli (simulado)")["incident_id"] is None


def test_fuzzy_inside_longer_words_and_new_tolerance():
    assert find("o perperito me pegou", [Rule("1", "perpe", fuzzy=True)])        # exato dentro da palavra
    assert find("ontem fique perpes feliz", [Rule("1", "perpe", fuzzy=True)])
    assert find("a perpa de ontem", [Rule("1", "perpe", fuzzy=True)])              # 1 letra diferente (5 letras: tolera 1)
    assert find("brocules", [Rule("1", "brocolis", fuzzy=True)])                    # 2 letras diferentes (8 letras: tolera 2)
    assert not find("brocalex", [Rule("1", "brocolis", fuzzy=True)])                # 3 edições: fora


def test_fuzzy_caps_distinct_words_and_stays_fast_on_huge_text():
    import time
    words = " ".join(f"palavra{i}x" for i in range(20000))
    t0 = time.perf_counter()
    find(words, [Rule(str(i), f"termo{i}teste", fuzzy=True) for i in range(40)])
    assert time.perf_counter() - t0 < 5.0
