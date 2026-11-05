import pytest

from promptshield_detection import analyze

ner_mod = pytest.importorskip("promptshield_detection.ner")
try:
    NER = ner_mod.NerDetector()
except ner_mod.NerUnavailableError:  # extra [ner] ou modelos do spaCy ausentes
    pytest.skip("Presidio/spaCy ou modelos ausentes", allow_module_level=True)


def ev(text):
    return {"kind": "prompt", "content": {"text": text}}


def test_full_name_is_pii_and_masked():
    a = analyze(ev("Preciso falar com Maria Fernanda Souza sobre o contrato."), ner=NER)
    assert "pii" in a.category_ids()
    assert "Maria Fernanda" not in a.masked_text


def test_company_name_in_copyright_is_not_a_person():
    a = analyze(ev("# Copyright (c) 2026 Empresa Exemplo Ltda. Uso interno."), ner=NER)
    assert "pii" not in a.category_ids()


def test_city_and_single_first_name_are_not_pii():
    assert "pii" not in analyze(ev("São Paulo é a maior cidade do Brasil."), ner=NER).category_ids()
    assert "pii" not in analyze(ev("Ligue para a Marina amanhã"), ner=NER).category_ids()


def test_address_and_cep_do_not_need_ner():
    a = analyze(ev("Moro na Rua das Flores, 123, CEP 01310-100."))
    assert "pii" in a.category_ids()
    assert "Rua das Flores" not in a.masked_text
