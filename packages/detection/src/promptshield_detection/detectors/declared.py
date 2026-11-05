"""Componente B: dados sensíveis DECLARADOS em linguagem natural, sem prefixo de fornecedor.

"meu token é 43954jjsed94523mfdw", "mi contraseña es ...", "ag 3526 cc 9.856.456-6", "meu cartão é 4111 1111 1111 1112".
A regra tem três partes, todas obrigatórias, para separar o segredo REALMENTE presente da simples menção a ele:
  1. um SUBSTANTIVO do dicionário (token, chave de api, agência, conta, cartão, chave privada...), tolerando erro de digitação e abreviação;
  2. um CONECTOR (":", "=", "é", "is", "es", "segue"...) logo depois, até três palavras de enchimento ("de acesso", "da api");
  3. um VALOR com a forma de um segredo (mistura de letras e dígitos, entropia, tamanho), que não seja placeholder nem esteja ofuscado.
Sem valor ("como renovo meu token?") não há achado. Com asteriscos ou "xxxx" no valor (a própria pessoa ofuscou) não há achado.
Roda no texto normalizado (minúsculo, sem acento, mesmo tamanho) para achar a estrutura e lê o valor no texto ORIGINAL (maiúsculas contam para a entropia).
Português, inglês e espanhol. Nada aqui bloqueia ou altera o texto: só produz achados com trechos para mascarar.
"""
from __future__ import annotations

import re

from ..models import Context, Finding
from ..validators import card_plausible, digits, entropy
from .secrets import is_placeholder

CONN = r"(?:\s*(?::|=>|=|->|—|–|-)\s*|\s+(?:e|eh|es|is|are|era|sera|seria|foi|was|segue|follows?|abaixo|below|aqui|here)\b\s*:?\s*)"
FILL = r"(?:\s+(?:de|do|da|del|dos|das|of|for|para|pra|acesso|access|api|auth|bearer|banco|bancaria|bancario|bank|numero|number|no|n)){0,3}"

SECRET_NOUN = (
    r"(?:tok[ea]?n{1,2}s?|toke|toke?m+s?|toquen|api[\s_-]?keys?|apikeys?"
    r"|chaves?\s+(?:de\s+|da\s+|do\s+)?(?:api|acesso|secreta|segura)|claves?\s+(?:de\s+|da\s+)?(?:api|acceso|secreta)|llaves?\s+(?:de\s+)?(?:api|acceso)"
    r"|(?:access|secret|auth|refresh|bearer|session)[\s_-]?(?:key|token|secret)s?|client[\s_-]?secret|secrets?|segredos?|credenciais|credencial|credentials?)"
)
POSSESSIVE = re.compile(r"(?:meu|minha|meus|minhas|my|mi|mis)\s+(?:\w+\s+){0,2}$")
SECRET_RE = re.compile(rf"(?<![a-z0-9_])(?P<noun>{SECRET_NOUN}){FILL}{CONN}(?P<val>[a-z0-9_\-+/=.]{{8,300}})(?![a-z0-9_])")
SECRET_ADJACENT_RE = re.compile(rf"(?<![a-z0-9_])(?P<noun>{SECRET_NOUN}){FILL}\s+(?P<val>[a-z0-9_\-+/=.]{{16,300}})(?![a-z0-9_])")

# valores que parecem segredo mas são exemplos genéricos
FAKE_VALUES = {"abc123", "abc1234", "abc123xyz", "abcd1234", "123456", "1234567890", "password123", "senha123", "token123", "teste123", "test123",
               "example123", "exemplo123", "qwerty123", "changeme123", "secret123", "minhasenha123", "mypassword123"}


def _value_ok(core: str, min_len: int) -> bool:
    if len(core) < min_len or len(core) > 300 or "*" in core or "://" in core or is_placeholder(core):
        return False
    if core.lower() in FAKE_VALUES or re.search(r"(?i)x{4,}|\.{3,}|(.)\1{5,}", core):
        return False
    has_letter, has_digit = bool(re.search(r"[A-Za-z]", core)), bool(re.search(r"\d", core))
    has_upper, has_lower = bool(re.search(r"[A-Z]", core)), bool(re.search(r"[a-z]", core))
    if not ((has_letter and has_digit) or (has_upper and has_lower and len(core) >= 16)):
        return False                       # só letras (uma palavra) ou só dígitos (data, telefone, número de pedido) não é token
    if len(set(core)) < 6:
        return False
    return entropy(core) >= (2.7 if len(core) < 16 else 3.1)


def _secret_findings(t: str, f: str) -> list[Finding]:
    out: list[Finding] = []
    for rx, explicit in ((SECRET_RE, True), (SECRET_ADJACENT_RE, False)):
        for m in rx.finditer(f):
            s, e = m.start("val"), m.end("val")
            core = t[s:e].rstrip(".,;:)'\"")
            first_person = bool(POSSESSIVE.search(f[max(0, m.start("noun") - 30):m.start("noun")]))
            if not _value_ok(core, 8 if first_person and explicit else 12):
                continue
            conf = 0.8 + (0.05 if first_person else 0) + (0.05 if len(core) >= 20 else 0) + (0.05 if re.search(r"[:=]", f[m.end("noun"):s]) else 0)
            if not explicit:
                conf = 0.8 if first_person else 0.7      # sem conector ("here is my api key X"): com "meu/my/mi" ainda é explícito
            out.append(Finding("segredo", min(conf, 0.92), "Possível token ou chave informado em contexto explícito", "declared_token", s, s + len(core), "[TOKEN]"))
    return out


# ---- dados bancários ----
AG_NOUN = r"(?:agenc(?:ia|y)|agg|ag|branch|sucursal|oficina)\.?"
AC_NOUN = (r"(?:conta(?:\s+(?:corrente|poupanca|salario|pagamento))?|c/c|c\.c\.?|cc|cta|c\.?\s?poup|account(?:\s+(?:number|no\.?))?|acct|"
           r"cuenta(?:\s+(?:corriente|de\s+ahorros))?|n(?:umero)?\s+da\s+conta)")
AG_VAL = r"(?P<ag>\d{3,5}(?:-[0-9x])?)(?![\d.])"
AC_VAL = r"(?P<ac>\d{1,3}(?:\.\d{3}){1,2}-?[0-9x]|\d{4,12}-[0-9x]|\d{5,12})(?![\d-])"
BANK_AG_AC = re.compile(rf"(?<![a-z0-9])(?:{AG_NOUN})[^\d\n]{{0,12}}?{AG_VAL}[^\d\n]{{0,30}}?(?<![a-z0-9])(?:{AC_NOUN})[^\d\n]{{0,12}}?{AC_VAL}")
BANK_AC_AG = re.compile(rf"(?<![a-z0-9])(?:{AC_NOUN})[^\d\n]{{0,12}}?{AC_VAL}[^\d\n]{{0,30}}?(?<![a-z0-9])(?:{AG_NOUN})[^\d\n]{{0,12}}?{AG_VAL}")
ACCOUNT_ALONE = re.compile(rf"(?<![a-z0-9])(?:{AC_NOUN})[^\d\n]{{0,12}}?(?P<ac>\d{{1,3}}(?:\.\d{{3}}){{1,2}}-[0-9x]|\d{{4,12}}-[0-9x])(?![\d-])")

# ---- cartão em contexto explícito (o detector de Luhn já pega os válidos; aqui entram os com dígito errado) ----
CARD_NOUN = (r"(?:cart(?:ao|aao|oes|a)(?:\s+de\s+(?:credito|debito))?|credit\s+card|debit\s+card|card(?:\s+number)?|tarjeta(?:\s+de\s+(?:credito|debito))?|"
             r"n(?:umero)?\s+do\s+cartao)")
CARD_CTX = re.compile(rf"(?<![a-z0-9]){CARD_NOUN}[^\d\n]{{0,25}}?(?P<num>\d{{4}}(?:[ -]?\d{{3,4}}){{2,4}})(?![\d*])")
CVV_CTX = re.compile(r"(?<![a-z0-9])(?:cvv2?|cvc2?|cod(?:igo)?\s+de\s+seguranca|security\s+code)[^\d\n]{0,8}?(?P<cvv>\d{3,4})(?!\d)")

# ---- chave Pix com CPF/CNPJ formatado (o detector de Pix existente só pega chaves só de dígitos) ----
PIX_DOC = re.compile(r"(?<![a-z0-9])pix\b[^\n\d]{0,40}?(?P<key>\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})")

# ---- corpo de chave privada colado sem o cabeçalho ----
PRIVKEY_NOUN = r"(?:chave\s+privada|clave\s+privada|private\s+key|chave\s+ssh|ssh\s+key|id_rsa|pem)"
PRIVKEY_CTX = re.compile(rf"(?<![a-z0-9]){PRIVKEY_NOUN}{CONN}(?P<val>[a-z0-9+/=\n]{{40,}})")
DER_HEAD = re.compile(r"\bMII[A-Za-z0-9]{3}[A-Za-z0-9+/]{50,}={0,2}")   # PKCS#8/PKCS#1 em base64 sempre começa com MII


def _bank_findings(t: str, f: str) -> list[Finding]:
    out: list[Finding] = []
    taken: list[tuple[int, int]] = []
    for rx in (BANK_AG_AC, BANK_AC_AG):
        for m in rx.finditer(f):
            for g, label, typ in (("ag", "[AGENCIA]", "agencia"), ("ac", "[CONTA_BANCARIA]", "conta_bancaria")):
                out.append(Finding("financeiro", 0.8, "Agência e conta bancária informadas", typ, m.start(g), m.end(g), label))
            taken.append((m.start(), m.end()))
    for m in ACCOUNT_ALONE.finditer(f):
        if any(a <= m.start("ac") < b for a, b in taken):
            continue
        out.append(Finding("financeiro", 0.7, "Número de conta bancária informado", "conta_bancaria", m.start("ac"), m.end("ac"), "[CONTA_BANCARIA]"))
    return out


def _card_findings(t: str, f: str) -> list[Finding]:
    out: list[Finding] = []
    for m in CARD_CTX.finditer(f):
        d = digits(m.group("num"))
        if 13 <= len(d) <= 19 and not card_plausible(d) and len(set(d)) > 1:
            out.append(Finding("financeiro", 0.6, "Possível número de cartão (dígito verificador inválido, mas o texto diz que é um cartão)", "cartao",
                               m.start("num"), m.end("num"), "[CARTAO]"))
    for m in CVV_CTX.finditer(f):
        out.append(Finding("financeiro", 0.7, "CVV informado", "cvv", m.start("cvv"), m.end("cvv"), "[CVV]"))
    return out


def _pix_findings(t: str, f: str) -> list[Finding]:
    return [Finding("financeiro", 0.75, "Chave Pix (CPF ou CNPJ)", "pix", m.start("key"), m.end("key"), "[CHAVE_PIX]") for m in PIX_DOC.finditer(f)]


def _privkey_findings(t: str, f: str) -> list[Finding]:
    out: list[Finding] = []
    for m in PRIVKEY_CTX.finditer(f):
        body = t[m.start("val"):m.end("val")]
        if len(re.sub(r"\s", "", body)) >= 40 and not is_placeholder(body.strip()):
            out.append(Finding("segredo", 0.9, "Possível corpo de chave privada colado no texto", "private_key_body", m.start("val"), m.end("val"), "[CHAVE_PRIVADA]"))
    for m in DER_HEAD.finditer(t):
        out.append(Finding("segredo", 0.9, "Conteúdo em base64 com cabeçalho de chave privada (PKCS)", "private_key_body", m.start(), m.end(), "[CHAVE_PRIVADA]"))
    return out


def detect(ctx: Context) -> list[Finding]:
    if ctx.kind == "tool_call" or not ctx.text:
        return []
    t, f = ctx.text, ctx.folded
    return _secret_findings(t, f) + _bank_findings(t, f) + _card_findings(t, f) + _pix_findings(t, f) + _privkey_findings(t, f)
