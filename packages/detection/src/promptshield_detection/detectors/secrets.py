"""Segredos: formatos conhecidos, entropia perto de palavras-chave, exemplos de documentação."""
from __future__ import annotations

import re

from ..models import Context, Finding
from ..validators import entropy

DOC_EXAMPLES = {
    "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
}
PLACEHOLDER = re.compile(
    r"(?i)^(?:x{4,}|\*{3,}|\.{3,}|<.*>|\$\{.*\}|\{\{.*\}\}|your[-_ ]|change[-_]?me|example|exemplo|todo|"
    r"(?:placeholder|senha|password|secret|token|dummy)\w{0,4}$|test(?:e)?$)")   # "senha123" é exemplo; "SenhaDoBanco9" é senha de verdade

RULES: list[tuple[re.Pattern[str], str, str, float, str]] = [
    (re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}\b"), "aws_access_key", "Chave de acesso AWS", 0.97, "AKIA****"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "gcp_api_key", "Chave de API do Google", 0.93, "AIza****"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "github_token", "Token do GitHub", 0.98, "gh*_****"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "slack_token", "Token do Slack", 0.97, "xox*-****"),
    (re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b"), "stripe_key", "Chave Stripe de produção", 0.98, "sk_live_****"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "jwt", "JWT", 0.85, "eyJ****"),
    (re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----"), "private_key", "Chave privada", 0.99, "-----BEGIN ****-----"),
    (re.compile(r"AccountKey=[A-Za-z0-9+/]{40,}={0,2}"), "azure_storage_key", "Chave de conta Azure Storage", 0.96, "AccountKey=****"),
    (re.compile(r"(?i)\bsig=[A-Za-z0-9%+/]{30,}={0,2}"), "azure_sas", "Assinatura SAS do Azure", 0.9, "sig=****"),
    (re.compile(r"(?i)aws_secret_access_key\W{0,4}([A-Za-z0-9/+=]{40})\b"), "aws_secret_key", "Chave secreta AWS", 0.96, "****"),
    (re.compile(r'"private_key"\s*:\s*"-----BEGIN'), "gcp_service_account", "Service account do GCP", 0.98, '"private_key": "****'),
    # formatos adicionados na Etapa 10
    (re.compile(r"\bsk-ant-[^\s'\"`]{20,}"), "anthropic_key", "Chave de API da Anthropic", 0.98, "sk-ant-****"),
    (re.compile(r"\bwhsec_[^\s'\"`]{20,}"), "webhook_secret", "Segredo de webhook (whsec_)", 0.95, "whsec_****"),
    (re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}\b"), "openai_key", "Chave de API (formato sk-)", 0.95, "sk-****"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "npm_token", "Token do npm", 0.97, "npm_****"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20}\b"), "gitlab_token", "Token do GitLab", 0.97, "glpat-****"),
    (re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"), "sendgrid_key", "Chave do SendGrid", 0.97, "SG.****"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), "hf_token", "Token do Hugging Face", 0.96, "hf_****"),
    (re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}\b"), "pypi_token", "Token do PyPI", 0.98, "pypi-****"),
    (re.compile(r"\bdop_v1_[a-f0-9]{64}\b"), "do_token", "Token da DigitalOcean", 0.97, "dop_v1_****"),
    (re.compile(r"\bkey-[0-9a-f]{32}\b"), "mailgun_key", "Chave do Mailgun", 0.8, "key-****"),
    (re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{20,}"), "slack_webhook", "Webhook do Slack", 0.95, "https://hooks.slack.com/****"),
    (re.compile(r"https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[A-Za-z0-9_\-]{40,}"), "discord_webhook", "Webhook do Discord", 0.95, "https://discord.com/****"),
    (re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=\-]{24,})"), "bearer_token", "Token Bearer", 0.85, "****"),
]
CONN_RE = re.compile(r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*+://([^\s:@/]+):([^\s@/]{3,})@[^\s]+", re.I)
KEYWORD_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|senha|credential|access[_-]?key|auth)"
    r"[\w-]*\s*[:=]\s*[\"']?([A-Za-z0-9/+_\-=.]{16,})[\"']?")


# senha dita em frase ("a senha do root é X", "my password is X", "senha: X", "DB_PASSWORD=X")
# autenticação básica no comando: curl -u usuario:senha
BASIC_AUTH_RE = re.compile(r"(?:^|\s)(?:-u|--user)[ =]+['\"]?[\w.@-]+:([^\s'\"]{6,})")
PASSWORD_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:senha|password|passwd|pwd|passcode|pass)(?![A-Za-z])[^\n:=@/]{0,40}?(?:[:=]|\b(?:[eé]|eh|is|are|seria|set to|igual a)\b)\s*[\"'`]?([^\s\"'`,;]{6,64})")
COMMON_WORDS = {"required", "obrigatoria", "obrigatorio", "necessaria", "necessario", "important", "importante", "esquecida", "expired",
                "expirada", "wrong", "incorreta", "invalida", "invalid", "correct", "correta", "forgotten", "protected", "protegida",
                "stored", "armazenada", "hashed", "criptografada", "encrypted", "reset", "manager", "gerenciador", "policy", "politica",
                "minimum", "minima", "enabled", "disabled", "empty", "vazia", "default", "padrao", "admin123"}


def _password_like(value: str) -> bool:
    """Parece uma senha de verdade: mistura classes de caracteres ou é longa e variada, e não é palavra comum nem placeholder."""
    v = value.strip(".,)")
    if len(v) < 6 or v.lower() in COMMON_WORDS or _placeholder(v) or v.startswith(("<", "$", "{", "%", "[")):
        return False
    classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    pure_word = bool(re.fullmatch(r"[A-Z]?[a-z]+", v))
    return (classes >= 3 and entropy(v) >= 2.5) or (classes >= 2 and len(v) >= 10 and entropy(v) >= 2.8 and not pure_word)


def _placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.match(value)) or len(set(value)) <= 3


def detect(ctx: Context) -> list[Finding]:
    t, out, taken = ctx.text, [], []
    for rx, span_type, rule, conf, masked in RULES:
        for m in rx.finditer(t):
            value = m.group(1) if m.groups() else m.group(0)
            c = conf
            if value in DOC_EXAMPLES or "EXAMPLE" in value:
                c, rule_txt = 0.25, rule + " (igual ao exemplo da documentação)"
            elif len(value.split("_", 1)[-1]) >= 8 and _placeholder(value.split("_", 1)[-1]):
                c, rule_txt = 0.2, rule + " (placeholder)"
            else:
                rule_txt = rule
            s, e = (m.start(1), m.end(1)) if m.groups() else (m.start(), m.end())
            out.append(Finding("segredo", c, rule_txt, span_type, s, e, masked))
            taken.append((s, e))
    for m in CONN_RE.finditer(t):
        if _placeholder(m.group(2)) or m.group(2).startswith(("$", "{", "<")):
            continue
        out.append(Finding("segredo", 0.9, "String de conexão com senha", "conn_string",
                           m.start(), m.end(), "****://usuario:****@…"))
        taken.append((m.start(), m.end()))
    for m in KEYWORD_RE.finditer(t):
        value = m.group(1)
        if any(a <= m.start(1) < b for a, b in taken) or value in DOC_EXAMPLES:
            continue
        if _placeholder(value) or entropy(value) < 3.3:
            continue
        out.append(Finding("segredo", 0.8, "Valor de alta entropia perto de palavra-chave de segredo",
                           "high_entropy", m.start(1), m.end(1), value[:2] + "****"))
    for m in BASIC_AUTH_RE.finditer(t):
        value = m.group(1)
        if any(a <= m.start(1) < b for a, b in taken) or _placeholder(value) or value.startswith(("$", "{", "<", "%")):
            continue
        out.append(Finding("segredo", 0.85, "Usuário e senha na linha de comando (-u)", "password", m.start(1), m.end(1), "****"))
        taken.append((m.start(1), m.end(1)))
    for m in PASSWORD_RE.finditer(t):
        value = m.group(1)
        if any(a <= m.start(1) < b for a, b in taken) or value in DOC_EXAMPLES or not _password_like(value):
            continue
        out.append(Finding("segredo", 0.85, "Senha informada no texto", "password", m.start(1), m.end(1), "****"))
        taken.append((m.start(1), m.end(1)))
    return out
