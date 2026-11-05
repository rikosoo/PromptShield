"""PII brasileira e dados financeiros. Presidio (nomes e endereços) NÃO está ligado: pendente."""
from __future__ import annotations

import re

from ..models import Context, Finding
from ..validators import aba_valid, card_plausible, cnpj_valid, cpf_valid, digits, iban_valid

CPF_RE = re.compile(r"(?<![\d.\-/])(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?![\d]|[.\-/]\d)")
CNPJ_RE = re.compile(r"(?<![\d.\-/])(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})(?![\d]|[.\-/]\d)")
# (?<![\w.+-]) e ++: só começa no início de uma sequência e não volta atrás (senão texto longo sem @ é quadrático)
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]++@[\w-]+(?:\.[\w-]+)+\b")
PHONE_RE = re.compile(r"(?<![\d])(?:\+55[ -]?)?\(?\d{2}\)?[ -]?9?\d{4}[ -]\d{4}(?!\d)|\+55\d{10,11}")
RG_RE = re.compile(r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}-?[\dxX](?![\d])")
CARD_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
BANK_RE = re.compile(r"ag[eê]ncia\W{0,3}\d{3,5}\W{0,12}conta\W{0,3}\d{4,}-?\d?", re.I)
# Número declarado como documento ("meu cpf é 3444353432123"): é dado pessoal mesmo com dígito inválido,
# erro de digitação ou tamanho errado. Só vale quando a palavra vem ANTES do número.
def _edit1(word: str, exclude: tuple[str, ...] = ()) -> str:
    """Alternância regex com a palavra e todas as variações de UM erro de digitação (troca, falta, sobra, letras trocadas de lugar):
    "cpfg", "cfp", "cpff" valem como "cpf". `exclude` tira variações que são outras palavras (ex.: "cpu")."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    out = {word}
    for i in range(len(word) + 1):
        out.update(word[:i] + c + word[i:] for c in letters)
    for i in range(len(word)):
        out.add(word[:i] + word[i + 1:])
        out.update(word[:i] + c + word[i + 1:] for c in letters)
        if i < len(word) - 1:
            out.add(word[:i] + word[i + 1] + word[i] + word[i + 2:])
    return "|".join(re.escape(w) for w in sorted((w for w in out if len(w) >= 3 and w not in exclude), key=lambda w: (-len(w), w)))


CPF_DECL_RE = re.compile(r"(?i)\b(?:" + _edit1("cpf", ("cpu", "cpp", "cpa", "cps", "cpt", "cpm", "cpl", "cpc", "cap", "cop")) + r"|c\.p\.f|c p f)\b[^\d\n.;]{0,20}?(\d[\d.\-]{6,17}\d)")
CNPJ_DECL_RE = re.compile(r"(?i)\b(?:" + _edit1("cnpj") + r")\b[^\d\n.;]{0,20}?(\d[\d.\-/]{9,20}\d)")
# "documento do cliente: 11122233355": 9 a 14 dígitos seguidos declarados como documento (confiança menor: pode ser número de protocolo)
DOC_DECL_RE = re.compile(r"(?i)\b(?:documento|identificacao|identificação)\b[^\d\n.;]{0,25}?(\d{9,14})(?!\d)")
RG_DECL_RE = re.compile(r"(?i)\b(?:rg|identidade|registro geral)\b[^\d\n.;]{0,15}?(\d[\d.\-]{4,13}[\dxX])")
EMAIL_EXAMPLE_CTX = re.compile(r"\b(?:placeholder|exemplos?|example|sample|ficticio|ficticia|fictitious|fake|dummy|documentacao|documentation|docs|nos testes|in the tests)\b")
PIX_RE = re.compile(r"(?i)\bpix\b[^\n]{0,40}?(?:chave\W{0,3})?(?P<key>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\w.+-]+@[\w-]+\.[\w.]+|\+55\d{10,11}|\d{8,14})(?!\d)")
BANK_REV_RE = re.compile(r"conta\W{0,3}\d{4,}-?\d?\W{0,12}ag[eê]ncia\W{0,3}\d{3,5}", re.I)
CEP_RE = re.compile(r"(?<![\d-])\d{5}-\d{3}(?![\d-])")
ADDR_PT_RE = re.compile(
    r"\b(?:Rua|R\.|Avenida|Av\.|Alameda|Travessa|Pra[çc]a|Estrada|Rodovia)\s+[^,\n\d]{3,50}?,?\s*(?:n[ºo°.]?\s*)?\d{1,5}\b")
ADDR_EN_RE = re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Drive)\b")
CTX_CPF = re.compile(r"cpf|c\.p\.f|cadastro de pessoa", re.I)
CTX_CNPJ = re.compile(r"cnpj", re.I)
CTX_RG = re.compile(r"\brg\b|identidade|registro geral", re.I)


# ---- ampliações (Etapa 10): separadores livres, documentos de outros países, contexto de telefone, PIX, IBAN ----
CPF_LOOSE_RE = re.compile(r"(?<![\d.\-/])(\d{3}[ .\-]\d{3}[ .\-]\d{3}[ .\-/]\d{2})(?![\d]|[.\-/]\d)")
CNPJ_LOOSE_RE = re.compile(r"(?<![\d.\-/])(\d{2}[ .]\d{3}[ .]\d{3}[ /]\d{4}[ \-]\d{2})(?![\d]|[.\-/]\d)")
PHONE_CTX_RE = re.compile(
    r"(?i)\b(?:whats(?:app)?|zap|tel(?:efone)?|cel(?:ular)?|fone|contato|phone|mobile|cell|call|ligar?|liga)\b"
    r"[^\d\n]{0,18}(\+?\d[\d ()\-]{8,17}\d)")
PHONE_INTL_RE = re.compile(r"(?<![\d\w])\+\d{1,3}[ \-]?\(?\d{1,4}\)?(?:[ \-]?\d{2,4}){2,4}(?!\d)")
PHONE_US_RE = re.compile(r"(?<![\d\w])(?:\+1[ \-]?)?\(?[2-9]\d{2}\)?[ .\-]\d{3}[ .\-]\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<![\d\-])(?!000|666|9\d\d)(\d{3})[- ](?!00)(\d{2})[- ](?!0000)(\d{4})(?![\d\-])")
CTX_SSN = re.compile(r"(?i)\bssn\b|social security|seguro social")
EIN_RE = re.compile(r"(?i)\b(?:ein|tax id|tin|federal tax)\b[^\d\n]{0,15}(\d{2}-\d{7})\b")
NI_RE = re.compile(r"(?i)\b(?:ni|national insurance)\b[^\n]{0,15}?\b([A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D])\b")
UK_POST_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
US_ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
US_ADDR_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Terrace|Way|Court|Ct|Place|Pl|Highway|Hwy)\b")
PASSPORT_RE = re.compile(r"(?i)\b(?:passport|passaporte)\b[^\n\d]{0,18}?([A-Z]{0,2}\d{6,9})\b")
LICENSE_RE = re.compile(r"(?i)\b(?:driver'?s? licen[sc]e|cnh|carteira (?:nacional de habilita[cç][aã]o|de motorista))\b[^\n\dA-Z]{0,25}([A-Z]?\d{7,12})\b")
VOTER_RE = re.compile(r"(?i)\bt[ií]tulo de eleitor\b[^\d\n]{0,10}(\d[\d ]{9,16}\d)")
DOB_RE = re.compile(
    r"(?i)(?:\bdob\b|date of birth|born (?:on|in)|\bnasc(?:imento|ido|ida|\.)?\b|data de nascimento)[^\d\n]{0,12}(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
ROUTING_RE = re.compile(r"(?i)\brouting(?: number)?\b[^\d\n]{0,10}(\d{9})\b")
ACCOUNT_RE = re.compile(r"(?i)\baccount(?: number| no\.?)?\b[^\d\n]{0,10}(\d{8,17})\b")
PIX_CTX = re.compile(r"(?i)\bpix\b")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
BANK2_RE = re.compile(r"(?i)\bag(?:[eê]ncia)?\.?\W{0,3}\d{3,5}\W{0,12}(?:c/?c|cc|c\.c\.|conta(?: corrente| poupan[cç]a)?)\W{0,3}\d{4,}-?\d?")
CONTA_RE = re.compile(r"(?i)\bconta (?:corrente|poupan[cç]a)\W{0,3}\d{4,}-?\d?")
# 0800, 0300 e afins são números de empresa (SAC), não de pessoa
NOT_PERSONAL_PREFIXES = ("0800", "0300", "0500", "0900", "4004", "4003", "3003")
# número só dígitos que parece telefone brasileiro (DDD + 8 ou 9 dígitos)
BR_MOBILE = re.compile(r"^(?:55)?[1-9]\d9?\d{8}$")


FORMAT_CTX = re.compile(r"(?i)\b(?:regex|regexp|format(?:o|ar|ting)?|validar|validate|validation|validacao|mascara|mask(?:ing)?|exemplo|example|placeholder|"
                        r"like|tipo|such as|e\.g\.|pattern|padrao)\b")
TOLL_FREE = re.compile(r"^(?:\+?1)?(?:800|833|844|855|866|877|888)")


def _format_example(t: str, start: int, end: int) -> bool:
    """Número dentro de uma pergunta sobre FORMATO ("regex para telefone como (555) 123-4567"): exemplo, não dado de pessoa."""
    return bool(FORMAT_CTX.search(t[max(0, start - 70):start] + " " + t[end:end + 70]))


def _placeholder_digits(value: str) -> bool:
    d = digits(value)
    return len(set(d)) <= 2 or d == "1234567890"


def _extra(t: str) -> list[Finding]:
    out: list[Finding] = []
    for m in CPF_LOOSE_RE.finditer(t):
        if cpf_valid(m.group(1)):
            out.append(Finding("pii", 0.92, "CPF com separadores variados e dígito verificador válido", "cpf",
                               m.start(1), m.end(1), "***.***.***-" + digits(m.group(1))[-2:]))
    for m in CNPJ_LOOSE_RE.finditer(t):
        if cnpj_valid(m.group(1)):
            out.append(Finding("pii", 0.92, "CNPJ com separadores variados", "cnpj", m.start(1), m.end(1),
                               "**.***.***/****-" + digits(m.group(1))[-2:]))
    for m in PHONE_CTX_RE.finditer(t):
        d = digits(m.group(1))
        if 10 <= len(d) <= 13 and not cpf_valid(d) and not d.startswith(NOT_PERSONAL_PREFIXES):
            out.append(Finding("pii", 0.8, "Telefone com contexto (whats, tel, call...)", "telefone", m.start(1), m.end(1),
                               "(**) *****-" + d[-4:]))
    for m in PHONE_INTL_RE.finditer(t):
        d = digits(m.group())
        if 9 <= len(d) <= 15:
            out.append(Finding("pii", 0.8, "Telefone internacional", "telefone", m.start(), m.end(), "+** ******" + d[-4:]))
    for m in PHONE_US_RE.finditer(t):
        if TOLL_FREE.match(digits(m.group())) or _format_example(t, m.start(), m.end()) or _placeholder_digits(m.group()):
            continue
        out.append(Finding("pii", 0.75, "Telefone dos EUA", "telefone", m.start(), m.end(), "(***) ***-" + digits(m.group())[-4:]))
    for m in SSN_RE.finditer(t):
        ctx = bool(CTX_SSN.search(t[max(0, m.start() - 40):m.start()]))
        out.append(Finding("pii", 0.92 if ctx or "-" in m.group() else 0.75, "SSN (número de seguro social dos EUA)", "ssn",
                           m.start(), m.end(), "***-**-" + m.group(3)))
    for rx, kind, label, masked in ((EIN_RE, "ein", "EIN (identificação fiscal dos EUA)", "[EIN]"),
                                    (NI_RE, "ni", "National Insurance (Reino Unido)", "[NI]"),
                                    (PASSPORT_RE, "passaporte", "Passaporte", "[passaporte]"),
                                    (LICENSE_RE, "cnh", "CNH ou driver's license", "[habilitação]"),
                                    (VOTER_RE, "titulo", "Título de eleitor", "[título]")):
        for m in rx.finditer(t):
            out.append(Finding("pii", 0.85, label, kind, m.start(1), m.end(1), masked))
    for m in DOB_RE.finditer(t):
        out.append(Finding("pii", 0.7, "Data de nascimento", "nascimento", m.start(1), m.end(1), "[data de nascimento]"))
    for m in US_ADDR_RE.finditer(t):
        out.append(Finding("pii", 0.78, "Street address", "endereco", m.start(), m.end(), "[endereço]"))
    for m in US_ZIP_RE.finditer(t):
        if re.search(r"\d{1,5}\s+\w+", t[max(0, m.start() - 60):m.start()]):  # só com um endereço antes (evita siglas soltas)
            out.append(Finding("pii", 0.72, "ZIP code com estado", "cep", m.start(), m.end(), "[ZIP]"))
    for m in UK_POST_RE.finditer(t):
        if re.search(r"(?i)postcode|post code|london|uk\b|reino unido", t):
            out.append(Finding("pii", 0.7, "Postcode do Reino Unido", "cep", m.start(), m.end(), "[postcode]"))
    for m in IBAN_RE.finditer(t):
        if iban_valid(m.group()):
            out.append(Finding("financeiro", 0.95, "IBAN com dígitos de controle válidos", "iban", m.start(), m.end(),
                               m.group()[:4] + " **** ****"))
    for m in ROUTING_RE.finditer(t):
        if aba_valid(m.group(1)):
            out.append(Finding("financeiro", 0.85, "Routing number (ABA) válido", "routing", m.start(1), m.end(1), "[routing]"))
    for m in ACCOUNT_RE.finditer(t):
        if ROUTING_RE.search(t):
            out.append(Finding("financeiro", 0.8, "Número de conta com routing number", "conta_bancaria", m.start(1), m.end(1), "[conta]"))
    for rx in (BANK2_RE, CONTA_RE):
        for m in rx.finditer(t):
            out.append(Finding("financeiro", 0.8, "Agência e conta bancária", "conta_bancaria", m.start(), m.end(), "[conta bancária]"))
    if PIX_CTX.search(t):
        for m in UUID_RE.finditer(t):
            out.append(Finding("financeiro", 0.8, "Chave PIX aleatória", "pix", m.start(), m.end(), "[chave pix]"))
        for m in re.finditer(r"(?<!\d)\d{10,11}(?!\d)", t):
            if BR_MOBILE.match(m.group()) and not cpf_valid(m.group()):
                out.append(Finding("financeiro", 0.8, "Chave PIX (telefone)", "pix", m.start(), m.end(), "[chave pix]"))
                out.append(Finding("pii", 0.75, "Telefone usado como chave PIX", "telefone", m.start(), m.end(), "(**) *****-" + m.group()[-4:]))
    return out


def _near(text: str, start: int, end: int, ctx: re.Pattern[str], window: int = 25) -> bool:
    return bool(ctx.search(text[max(0, start - window):end + 5]))


def detect(ctx: Context) -> list[Finding]:
    t, out = ctx.text, []
    for m in CPF_RE.finditer(t):
        raw = m.group(1)
        if not cpf_valid(raw):
            continue
        formatted = "." in raw
        if formatted:
            conf = 0.97
        elif _near(t, m.start(), m.end(), CTX_CPF):
            conf = 0.9
        else:
            conf = 0.55  # 11 dígitos válidos sem pontuação nem contexto: pode ser telefone
        out.append(Finding("pii", conf, "CPF com dígito verificador válido", "cpf",
                           m.start(1), m.end(1), "***.***.***-" + digits(raw)[-2:]))
    for m in CNPJ_RE.finditer(t):
        raw = m.group(1)
        if not cnpj_valid(raw):
            continue
        conf = 0.95 if "/" in raw or _near(t, m.start(), m.end(), CTX_CNPJ) else 0.6
        out.append(Finding("pii", conf, "CNPJ com dígito verificador válido", "cnpj",
                           m.start(1), m.end(1), "**.***.***/****-" + digits(raw)[-2:]))
    for m in RG_RE.finditer(t):
        if _near(t, m.start(), m.end(), CTX_RG, 20):
            out.append(Finding("pii", 0.85, "RG com contexto", "rg", m.start(), m.end(), "**.***.***-*"))
    for rx, lo, hi, kind, label, masked in (
        (CPF_DECL_RE, 9, 14, "cpf", "CPF informado (dígito verificador inválido ou formato incomum)", "[CPF]"),
        (CNPJ_DECL_RE, 12, 16, "cnpj", "CNPJ informado (dígito verificador inválido ou formato incomum)", "[CNPJ]"),
        (RG_DECL_RE, 6, 12, "rg", "RG informado", "[RG]"),
        (DOC_DECL_RE, 9, 14, "documento", "Número declarado como documento", "[DOC]"),
    ):
        for m in rx.finditer(t):
            if lo <= len(digits(m.group(1))) <= hi:
                out.append(Finding("pii", 0.6 if kind == "documento" else 0.8, label, kind, m.start(1), m.end(1), masked))
    from ..textnorm import fold
    folded = fold(t)
    for m in EMAIL_RE.finditer(t):
        near = folded[max(0, m.start() - 50):m.start()] + " " + folded[m.end():m.end() + 50]   # sem o próprio endereço ("exemplo.com.br" não vale)
        if EMAIL_EXAMPLE_CTX.search(near):   # "o placeholder do e-mail é joao@exemplo.com": exemplo de documentação, não pessoa
            continue
        out.append(Finding("pii", 0.75, "Endereço de e-mail", "email", m.start(), m.end(),
                           "***@" + m.group().split("@")[1]))
    for m in PHONE_RE.finditer(t):
        d = digits(m.group())
        if 10 <= len(d) <= 13:
            out.append(Finding("pii", 0.7, "Telefone brasileiro", "telefone", m.start(), m.end(),
                               "(**) *****-" + d[-4:]))
    for m in CARD_RE.finditer(t):
        d = digits(m.group())
        if card_plausible(d) and not (len(d) == 11 or cpf_valid(d)):
            out.append(Finding("financeiro", 0.93, "Número de cartão com Luhn válido", "cartao",
                               m.start(), m.end(), "**** **** **** " + d[-4:]))
    for m in ADDR_PT_RE.finditer(t):
        out.append(Finding("pii", 0.8, "Endereço residencial ou comercial", "endereco", m.start(), m.end(), "[endereço]"))
    for m in ADDR_EN_RE.finditer(t):
        out.append(Finding("pii", 0.75, "Street address", "endereco", m.start(), m.end(), "[endereço]"))
    for m in CEP_RE.finditer(t):
        if _placeholder_digits(m.group()) or _format_example(t, m.start(), m.end()):
            continue
        out.append(Finding("pii", 0.7, "CEP", "cep", m.start(), m.end(), "*****-***"))
    for m in BANK_RE.finditer(t):
        out.append(Finding("financeiro", 0.8, "Agência e conta bancária", "conta_bancaria",
                           m.start(), m.end(), "[conta bancária]"))
    for m in BANK_REV_RE.finditer(t):
        out.append(Finding("financeiro", 0.8, "Conta e agência bancária", "conta_bancaria", m.start(), m.end(), "[conta bancária]"))
    for m in PIX_RE.finditer(t):
        out.append(Finding("financeiro", 0.72, "Chave Pix", "pix", m.start("key"), m.end("key"), "[chave pix]"))
    out += _extra(t)
    # números dentro de um IBAN, cartão ou conta não são telefone nem CEP (evita contar o mesmo trecho duas vezes)
    out = [f for f in out if not (f.span_type in ("cpf", "cnpj", "rg", "cep", "telefone") and f.start is not None
                                  and _placeholder_digits(t[f.start:f.end]) and len(digits(t[f.start:f.end])) >= 5)]
    fin = [(f.start, f.end) for f in out if f.span_type in ("iban", "cartao", "routing", "conta_bancaria")]
    return [f for f in out if not (f.span_type in ("telefone", "cep") and (any(a <= f.start and f.end <= b for a, b in fin)
                                                                          or _format_example(t, f.start, f.end)))]
