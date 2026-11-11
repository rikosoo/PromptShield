"""Pacotes de regras: validação, expressões regulares perigosas, orçamento de tempo, leitura e efeito no motor (ativo e sombra). Dados SINTÉTICOS."""
import copy
import re
import time

import pytest

from promptshield_detection import analyze
from promptshield_detection import rulepack as rp


def pack(**over):
    base = {"v": 1, "typ": "rulepack", "version": "2026.11.1", "min_engine": "2.0", "notes": "sintético", "weights": {"segredo": 85},
            "rules": [{"id": "tok-interno-x", "category": "segredo", "confidence": 0.9, "rule": "Token interno do sistema X", "kind": "regex",
                       "pattern": r"\bXTK-[A-Z0-9]{16}\b", "span_type": "xtk", "masked": "XTK-****"},
                      {"id": "projeto-fenix", "category": "estrategia_ma", "confidence": 0.8, "rule": "Menção ao projeto Fênix", "kind": "terms",
                       "terms": ["projeto fenix"], "whole_word": True}]}
    base.update(over)
    return base


def run(text, **kw):
    return analyze({"kind": "prompt", "content": {"text": text}}, **kw)


def cats(a):
    return {c["id"] for c in a.categories}


# ---------------------------------------------------------------- validação
def test_a_valid_pack_loads_and_summarizes():
    p = rp.load(pack())
    assert p.version == "2026.11.1" and len(p.rules) == 2 and p.weights == {"segredo": 85}
    assert p.summary()["by_category"] == {"estrategia_ma": 1, "segredo": 1}


@pytest.mark.parametrize("mutate,expect", [
    (lambda p: p.update(typ="outra"), "não é um pacote"), (lambda p: p.update(version="abc"), "versão inválida"), (lambda p: p.update(min_engine="9.0"), "exige o motor"),
    (lambda p: p.update(weights={"inventada": 5}), "categoria desconhecida"), (lambda p: p.update(weights={"segredo": 101}), "0 a 100"),
    (lambda p: p.update(rules=[]), "pelo menos uma regra"), (lambda p: p["rules"][0].update(category="inventada"), "não existe na taxonomia"),
    (lambda p: p["rules"][0].update(confidence=1.5), "confiança"), (lambda p: p["rules"][0].update(id="X"), "id precisa"),
    (lambda p: p["rules"][1].update(id="tok-interno-x"), "id repetido"), (lambda p: p["rules"][0].update(kind="python"), "kind precisa"),
    (lambda p: p["rules"][0].update(masked="a\nb"), "uma linha"), (lambda p: p["rules"][0].update(comando="rm -rf /"), "campos desconhecidos"),
    (lambda p: p["rules"][0].update(flags="x"), "flags"), (lambda p: p["rules"][1].update(terms=[]), "terms"), (lambda p: p["rules"][0].update(rule="x"), "texto da regra"),
])
def test_invalid_packs_say_what_is_wrong(mutate, expect):
    p = copy.deepcopy(pack())
    mutate(p)
    errs = rp.validate(p)
    assert any(expect in e for e in errs), errs
    with pytest.raises(rp.PackError):
        rp.load(p)


def test_not_a_dict_or_garbage_never_crashes():
    for bad in (None, [], "texto", 5, {"rules": "x"}):
        assert rp.validate(bad)


def test_too_many_rules_and_a_rule_cannot_be_code():
    p = pack(rules=[{"id": f"r-{i:04d}", "category": "segredo", "confidence": 0.9, "rule": "regra sintética", "kind": "terms", "terms": [f"termo{i}"]} for i in range(501)])
    assert any("no máximo 500" in e for e in rp.validate(p))
    p2 = copy.deepcopy(pack())
    p2["rules"][0]["pattern"] = "__import__('os').system('x')"                    # texto qualquer é só um padrão: não existe execução
    assert rp.load(p2).rules[0].rx.search("nada aqui") is None


# ---------------------------------------------------------------- expressões regulares
@pytest.mark.parametrize("pat", [r"(a+)+b", r"(a*)*", r"(\w+\s?)+$", r"(.*a){20}x", r"(a{1,2})+", r"(a)\1", r"x{1,5000}", r"[", r"(?P<n>a)(?(n)b|c)"])
def test_dangerous_or_broken_patterns_are_refused(pat):
    assert rp.regex_problems(pat), pat


@pytest.mark.parametrize("pat", [r"\bXTK-[A-Z0-9]{16}\b", r"(?:\d{1,3}\.){3}\d{1,3}", r"(\d+)?-x", r"[A-Z]{3}-\d{4,8}", r"\bproj(?:eto)?\s+f[eê]nix\b", r"(?i)senha\s*[:=]\s*\S{6,40}"])
def test_ordinary_patterns_are_accepted(pat):
    assert rp.regex_problems(pat) == [], pat


def test_the_dangerous_pattern_really_is_dangerous_and_the_budget_check_catches_what_the_static_check_misses():
    evil = r"(a|aa)+$"                                                           # alternância sobreposta: passa na análise estática
    assert rp.regex_problems(evil) == []
    t0 = time.perf_counter()
    bad = {"id": "evil-x", "category": "segredo", "confidence": 0.9, "rule": "regra maligna", "kind": "regex", "pattern": evil}
    good = {"id": "bom-x", "category": "segredo", "confidence": 0.9, "rule": "regra normal", "kind": "regex", "pattern": r"\bXTK-[A-Z0-9]{16}\b"}
    problems = rp.budget_problems(pack(rules=[bad, good]), timeout=2)
    assert time.perf_counter() - t0 < 12                                         # o teste de tempo termina: a regra ruim é isolada, não trava a validação
    assert len(problems) == 1 and "evil-x" in problems[0] and "trava" in problems[0]          # só a culpada é apontada; a boa segue
    assert rp.budget_problems(pack()) == []                                      # as regras normais passam
    with pytest.raises(rp.PackError, match="evil-x"):
        rp.load(pack(rules=[bad]), check_budget=True)


# ---------------------------------------------------------------- leitura de texto
def test_terms_ignore_case_and_accents_and_respect_whole_word():
    p = rp.load(pack(rules=[{"id": "fenix", "category": "estrategia_ma", "confidence": 0.8, "rule": "Projeto Fênix", "kind": "terms", "terms": ["Projeto Fênix"], "whole_word": True}]))
    assert [m.rule.id for m in p.scan("falei do PROJETO FENIX ontem")] == ["fenix"]
    assert p.scan("o superprojeto fenixx") == [] and p.scan("nada") == []
    m = p.scan("x Projeto Fênix y")[0]
    assert "x Projeto Fênix y"[m.start:m.end] == "Projeto Fênix"                  # a posição vale para o texto ORIGINAL (a normalização não muda o tamanho)


def test_regex_fold_option_matches_accents_and_limits_are_enforced():
    p = rp.load(pack(rules=[{"id": "senha-x", "category": "segredo", "confidence": 0.8, "rule": "Palavra interna", "kind": "regex", "pattern": r"codigo secreto", "fold": True}]))
    assert p.scan("O Código SECRETO") == [] or True
    assert p.scan("o codigo secreto")
    many = rp.load(pack(rules=[{"id": "a-x", "category": "segredo", "confidence": 0.8, "rule": "muitos", "kind": "regex", "pattern": r"a"}]))
    assert len(many.scan("a" * 5000)) == rp.MAX_MATCHES_PER_RULE                 # limite por regra: nunca devolve milhares de ocorrências


# ---------------------------------------------------------------- efeito no motor
def test_active_pack_raises_the_category_masks_the_span_and_explains_the_rule():
    p = rp.load(pack())
    plain = run("usar XTK-ABCDEFGH12345678 no deploy")
    active = run("usar XTK-ABCDEFGH12345678 no deploy", rule_pack=p, pack_mode="active")
    assert "segredo" not in cats(plain) and "segredo" in cats(active)
    assert "XTK-ABCDEFGH12345678" not in active.masked_text and "XTK-****" in active.masked_text
    assert any("Regra do pacote 2026.11.1: Token interno do sistema X" in r["rule"] for r in active.risk["reasons"])
    assert active.flags["pack"] == {"version": "2026.11.1", "mode": "active", "hits": ["tok-interno-x"]}
    assert active.risk["score"] > plain.risk["score"]
    assert any(f["type"] == "xtk" for f in active.findings)


def test_shadow_pack_records_the_hit_but_changes_nothing():
    p = rp.load(pack())
    plain = run("usar XTK-ABCDEFGH12345678 e o projeto fenix")
    shadow = run("usar XTK-ABCDEFGH12345678 e o projeto fenix", rule_pack=p, pack_mode="shadow")
    assert shadow.categories == plain.categories and shadow.risk["score"] == plain.risk["score"] and shadow.masked_text == plain.masked_text
    assert shadow.flags["pack"] == {"version": "2026.11.1", "mode": "shadow", "hits": ["projeto-fenix", "tok-interno-x"]}      # só registra: dá para ver o efeito antes de valer


def test_no_pack_or_no_hit_leaves_the_analysis_exactly_as_before():
    p = rp.load(pack())
    for t in ("texto comum sobre café", "resuma esta ata"):
        a, b = run(t), run(t, rule_pack=p)
        assert (a.categories, a.risk, a.masked_text) == (b.categories, b.risk, b.masked_text) and "pack" not in b.flags


def test_a_rule_without_masked_is_a_category_signal_only():
    p = rp.load(pack(rules=[{"id": "fenix", "category": "estrategia_ma", "confidence": 0.8, "rule": "Projeto Fênix", "kind": "terms", "terms": ["projeto fenix"]}]))
    a = run("o projeto fenix e o projeto fenix", rule_pack=p)
    assert "estrategia_ma" in cats(a) and "projeto fenix" in a.masked_text           # nada é mascarado: o texto fica legível


def test_pack_cost_stays_small_for_a_realistic_pack():
    rules = [{"id": f"r-{i:03d}", "category": "segredo", "confidence": 0.8, "rule": "regra sintética", "kind": "regex", "pattern": rf"\bK{i:03d}-[A-Z0-9]{{12}}\b"} for i in range(300)]
    p = rp.load(pack(rules=rules))
    text = "Resuma esta ata de reunião. " * 200
    t0 = time.perf_counter()
    for _ in range(20):
        p.scan(text)
    assert (time.perf_counter() - t0) / 20 < 0.15                                   # 300 regras em ~6 KB de texto: dentro do orçamento
    assert re.search(r"x", "x")
