"""Financeiro no texto: chave de acesso de NF-e, linha digitável de boleto e volume de valores internos.

NF-e: 44 dígitos, UF (IBGE) + modelo (55/65...) + dígito verificador módulo 11. Boleto bancário: 47 dígitos, três campos com módulo 10.
A VERIFICAR: as regras acima seguem o padrão público do Brasil lido de memória, ainda NÃO conferido contra a especificação oficial
(Manual da NF-e/Receita e Manual de boletos/FEBRABAN). Por isso a confiança fica abaixo de uma credencial e há teste com números sintéticos.
O volume de valores é um sinal de CONTEXTO (várias cifras + vocabulário financeiro), nunca um valor isolado.
"""
from __future__ import annotations

import re

from ..models import Context, Finding
from ..textnorm import fold

UF_CODES = frozenset({11, 12, 13, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26, 27, 28, 29, 31, 32, 33, 35, 41, 42, 43, 50, 51, 52, 53})
NFE_MODELS = frozenset({55, 65})
NFE_RE = re.compile(r"(?<![\d])(?:\d{44}|(?:\d{4} ){10}\d{4})(?![\d])")
BOLETO_RE = re.compile(r"(?<![\d])(?:\d{5}\.\d{5} \d{5}\.\d{6} \d{5}\.\d{6} \d \d{14}|\d{47})(?![\d])")
MONEY = re.compile(r"(?:r\$|usd|us\$|\$)\s?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|r\$\s?\d{4,}(?:,\d{2})?")
FIN_TERMS = re.compile(r"\b(?:faturamento|receita|lucro|margem|ebitda|prejuizo|orcamento|balanco|fluxo de caixa|divida|custo|resultado|"
                       r"forecast|budget|revenue|profit|dre|inadimplencia|projecao|ebit|capex|opex)\b")
SECRECY = re.compile(r"\b(?:confidencial|confidential|interno|internal|nao divulgar|sigilo\w*|restrito|do not share)\b")
MIN_VALUES, MIN_TERMS = 3, 2


def nfe_valid(key: str) -> bool:
    d = re.sub(r"\D", "", key)
    if len(d) != 44 or int(d[:2]) not in UF_CODES or int(d[20:22]) not in NFE_MODELS:
        return False
    total, w = 0, 2
    for ch in reversed(d[:43]):
        total += int(ch) * w
        w = 2 if w == 9 else w + 1
    r = total % 11
    return int(d[43]) == (0 if r in (0, 1) else 11 - r)


def _mod10(field: str) -> bool:
    data, dv = field[:-1], int(field[-1])
    total, w = 0, 2
    for ch in reversed(data):
        p = int(ch) * w
        total += p // 10 + p % 10
        w = 1 if w == 2 else 2
    return dv == (10 - total % 10) % 10


def boleto_valid(line: str) -> bool:
    d = re.sub(r"\D", "", line)
    return len(d) == 47 and _mod10(d[0:10]) and _mod10(d[10:21]) and _mod10(d[21:32])


def detect(ctx: Context) -> list[Finding]:
    t, out = ctx.text, []
    for m in NFE_RE.finditer(t):
        if nfe_valid(m.group()):
            out.append(Finding("financeiro", 0.92, "Chave de acesso de nota fiscal eletrônica (dígito verificador válido)", "nfe_key",
                               m.start(), m.end(), "[CHAVE_NFE]"))
    for m in BOLETO_RE.finditer(t):
        if boleto_valid(m.group()):
            out.append(Finding("financeiro", 0.85, "Linha digitável de boleto (dígitos verificadores válidos)", "boleto",
                               m.start(), m.end(), "[BOLETO]"))
    low = fold(t)
    if len(MONEY.findall(low)) >= MIN_VALUES and len({m.group() for m in FIN_TERMS.finditer(low)}) >= MIN_TERMS:
        conf = 0.75 if SECRECY.search(low) else 0.6
        out.append(Finding("financeiro", conf, "Várias cifras com vocabulário financeiro" + (" e marca de sigilo" if conf > 0.6 else "")))
    return out
