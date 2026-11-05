"""Intenção do pedido (PT e EN), por regras. Frases SINTÉTICAS."""
import pytest

from promptshield_detection import analyze


def intents(text: str, kind: str = "prompt") -> set[str]:
    return set(analyze({"kind": kind, "content": {"text": text}, "context": {}}).flags["intents"])


@pytest.mark.parametrize("text,expected", [
    ("Resuma este contrato em 3 linhas", {"resumir"}),
    ("please summarize the attached report", {"resumir"}),
    ("Traduza para inglês: bom dia", {"traduzir"}),
    ("Translate this to Portuguese", {"traduzir"}),
    ("revise meu código, não funciona", {"revisar_corrigir"}),
    ("can you fix this bug", {"revisar_corrigir"}),
    ("Escreva uma função em Python que ordena uma lista", {"gerar_codigo"}),
    ("write a SQL query to list users", {"gerar_codigo"}),
    ("explique como funciona o OAuth", {"explicar"}),
    ("Reescreva o texto de forma mais clara", {"reescrever_melhorar"}),
    ("Valide este CPF", {"validar_verificar"}),
    ("Escreva um e-mail para o cliente", {"redigir_texto"}),
])
def test_requests_are_recognized(text, expected):
    assert expected <= intents(text)


def test_user_declaring_content_confidential_is_a_signal():
    assert "declara_confidencial" in intents("o codigo e confidencial, queria melhorar por ser segredo")
    assert "declara_confidencial" in intents("this is confidential, please review it")


def test_unknown_phrase_has_no_intent_and_tool_calls_never_do():
    assert intents("bom dia") == set()
    assert intents("rm -rf ./tmp", kind="tool_call") == set()
