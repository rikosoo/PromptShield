"""Novas regras: arquivos (extensão, tipo, tamanho), financeiro no texto (NF-e, boleto, volume de cifras) e código. Dados SINTÉTICOS (simulados)."""
import pytest

from promptshield_detection import analyze
from promptshield_detection.detectors.financial import _mod10, boleto_valid, nfe_valid

MB = 1024 * 1024


def files(*items):
    atts = [{"name": n, **({"size": s} if s is not None else {}), **({"mime": m} if m else {})} for n, s, m in items]
    return analyze({"kind": "file_upload", "content": {"text": "", "attachments": atts}})


def cats(a):
    return {c["id"] for c in a.categories}


def make_nfe(uf="35", model="55") -> str:
    body = uf + "2301" + "12345678000195" + model + "001" + "000000123" + "1" + "12345678"   # 43 dígitos sintéticos
    assert len(body) == 43
    total, w = 0, 2
    for ch in reversed(body):
        total += int(ch) * w
        w = 2 if w == 9 else w + 1
    r = total % 11
    return body + str(0 if r in (0, 1) else 11 - r)


def make_boleto() -> str:
    def field(data):
        total, w = 0, 2
        for ch in reversed(data):
            p = int(ch) * w
            total += p // 10 + p % 10
            w = 1 if w == 2 else 2
        return data + str((10 - total % 10) % 10)
    return field("341911234") + field("5678901234") + field("5678901234") + "1" + "12340000015000"[:14].rjust(14, "0")


# ---------------------------------------------------------------- arquivos
@pytest.mark.parametrize("name,cat", [
    ("main.py", "codigo_proprietario"), ("Servico.java", "codigo_proprietario"), ("deploy.ps1", "codigo_proprietario"),
    ("main.tf", "iac"), ("Dockerfile", "iac"), ("extrato.ofx", "financeiro"), ("NF-e 35230112345.xml", "financeiro"),
    ("boleto-maio.pdf", "financeiro"), ("irpf-2025.pdf", "financeiro"), ("cpf.jpg", "pii"), ("curriculo-ana.docx", "pii"),
    ("CNH_frente.png", "pii"), ("atestado.pdf", "saude"), ("exame-sangue.pdf", "saude"), ("rescisao.pdf", "rh"),
    ("admissao-2026.pdf", "rh"), (".npmrc", "segredo"), ("sessao.har", "segredo"), ("dump.hprof", "segredo"),
    ("captura.pcap", "logs"), ("diagrama-de-rede.vsdx", "arquitetura"), ("caixa.pst", "cliente"), ("patente-v2.docx", "propriedade_intelectual"),
])
def test_file_type_and_name_rules(name, cat):
    assert cat in cats(files((name, 1000, None)))


def test_size_makes_big_data_files_a_signal_and_small_ones_not():
    assert "cliente" in cats(files(("dados.csv", 8 * MB, None)))
    assert "cliente" in cats(files(("tabela.xlsx", 6 * MB, None)))
    assert cats(files(("dados.csv", 20_000, None))) == set()
    assert cats(files(("dados.csv", None, None))) == set()


def test_mime_used_when_name_has_no_extension():
    assert "codigo_proprietario" in cats(files(("script", 100, "text/x-python")))
    assert "cliente" in cats(files(("export", 9 * MB, "text/csv")))


def test_name_size_and_mime_are_saved():
    a = files(("balanco-2026.xlsx", 123456, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    assert a.attachments == [{"name": "balanco-2026.xlsx", "size": 123456, "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}]
    assert files(("a.txt", True, None)).attachments[0]["size"] is None       # booleano não é tamanho
    assert files(("a.txt", -5, None)).attachments[0]["size"] is None


@pytest.mark.parametrize("name", ["foto-ferias.png", "relatorio.pdf", "ata-reuniao.docx", "resume-meeting.txt", "apresentacao.pptx", "exemplo.json", "musica.mp3"])
def test_harmless_files_stay_clean(name):
    assert cats(files((name, 50_000, None))) == set()


def test_code_file_stays_in_low_band():
    assert 0 < files(("main.py", 1000, None)).risk["score"] < 25     # decisão do dono: código compartilhado é risco baixo
    assert files(("extrato.ofx", 1000, None)).risk["score"] >= 25


# ---------------------------------------------------------------- financeiro no texto
def test_nfe_key_valid_and_invalid():
    k = make_nfe()
    assert nfe_valid(k) and not nfe_valid(k[:-1] + str((int(k[-1]) + 1) % 10))
    assert not nfe_valid(make_nfe(uf="99")) and not nfe_valid(make_nfe(model="10"))
    a = analyze({"kind": "prompt", "content": {"text": f"consulte a nota {k} por favor (simulado)"}})
    assert "financeiro" in cats(a) and k not in a.masked_text and "[CHAVE_NFE]" in a.masked_text
    spaced = " ".join(k[i:i + 4] for i in range(0, 44, 4))
    assert "financeiro" in cats(analyze({"kind": "prompt", "content": {"text": f"chave {spaced}"}}))
    bad = k[:-1] + str((int(k[-1]) + 1) % 10)
    assert "financeiro" not in cats(analyze({"kind": "prompt", "content": {"text": f"pedido {bad}"}}))


def test_boleto_line_valid_and_invalid():
    b = make_boleto()
    assert boleto_valid(b) and _mod10(b[0:10])
    pretty = f"{b[0:5]}.{b[5:10]} {b[10:15]}.{b[15:21]} {b[21:26]}.{b[26:32]} {b[32]} {b[33:]}"
    a = analyze({"kind": "prompt", "content": {"text": f"pague {pretty} ate sexta (simulado)"}})
    assert "financeiro" in cats(a) and "[BOLETO]" in a.masked_text
    broken = b[:9] + str((int(b[9]) + 1) % 10) + b[10:]
    assert "financeiro" not in cats(analyze({"kind": "prompt", "content": {"text": f"numero {broken}"}}))


def test_money_volume_needs_values_and_financial_words():
    t = "Resultado do trimestre: receita R$ 4.500.000,00, custo R$ 2.100.000,00, lucro R$ 1.200.000,00 (simulado)"
    a = analyze({"kind": "prompt", "content": {"text": t}})
    assert "financeiro" in cats(a)
    secret = analyze({"kind": "prompt", "content": {"text": t + " CONFIDENCIAL, nao divulgar"}})
    assert dict((c["id"], c["confidence"]) for c in secret.categories)["financeiro"] > dict((c["id"], c["confidence"]) for c in a.categories)["financeiro"]
    assert "financeiro" not in cats(analyze({"kind": "prompt", "content": {"text": "O cafe custou R$ 12,50 e o almoco R$ 35,00"}}))
    assert "financeiro" not in cats(analyze({"kind": "prompt", "content": {"text": "Explique o que e margem e lucro em uma empresa"}}))


# ---------------------------------------------------------------- código
@pytest.mark.parametrize("snippet", [
    "fn main() {\n    let mut total = 0;\n    use std::io;\n}",
    "<?php\nclass A { function f() { return $this->x; } }",
    "using System;\nnamespace App { class P { static void Main() { Console.WriteLine(1); } } }",
    "fun main() {\n  val x = 1\n  println(x)\n}",
    "import SwiftUI\nfunc hello() { guard let a = b else { return } }",
])
def test_more_languages_count_as_code(snippet):
    a = analyze({"kind": "prompt", "content": {"text": snippet}})
    assert a.flags["has_code"] is True and 0 < a.risk["score"] < 25


def test_more_proprietary_markers_in_code():
    code = "# All rights reserved. Do not distribute.\ndef calcula_preco(x):\n    return x * 2\n"
    assert "codigo_proprietario" in cats(analyze({"kind": "prompt", "content": {"text": code}}))
    plain = "class Carro:\n    def andar(self):\n        return 'propriedade da classe'\n"
    assert not any(c["confidence"] >= 0.7 for c in analyze({"kind": "prompt", "content": {"text": plain}}).categories if c["id"] == "codigo_proprietario")
