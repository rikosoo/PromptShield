"""Documento declarado com erro de digitação ou sem pontuação. Números SINTÉTICOS."""
import pytest

from promptshield_detection import analyze


def run(text):
    a = analyze({"kind": "prompt", "content": {"text": text}, "context": {}})
    return a.category_ids(), a.masked_text


@pytest.mark.parametrize("text", [
    "meu cpfg é 11122233355", "meu cpff 11122233355", "meu cfp é 11122233355", "meu cpg: 111.222.333-55", "meu ccpf 11122233355",
    "o cnpjj da empresa é 12345678000199", "cnpf: 11222333000181",
    "documento do cliente: 11122233355", "documento 123456789012",
])
def test_typo_or_documento_is_personal_data(text):
    cats, masked = run(text)
    assert "pii" in cats, text
    assert "11122233355" not in masked and "123456789012" not in masked and "12345678000199" not in masked


@pytest.mark.parametrize("text", [
    "o cpu está em 95% e a memória 12345678901 bytes", "cpu 11122233355 ciclos", "rode cpp 11122233355", "pedido 12345678901 do cliente",
    "o documento foi enviado ontem", "documento anexo, 3 páginas",
])
def test_no_false_alarm_on_common_words_or_numbers_without_context(text):
    assert "pii" not in run(text)[0], text
