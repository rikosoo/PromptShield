"""Infraestrutura mencionada no texto: endereços IP, hosts internos, caminhos com nome de usuário e nomes de arquivos sensíveis.

Tudo por regras locais (sem rede, sem LLM). Limites honestos: o IP e o host sugerem a rede da empresa, não provam; o nome de um arquivo
sugere, não prova (ver files.py). Só vale para texto de pessoa (prompt, resposta, upload): em chamada de ferramenta de agente o comando
já passa pelas regras de ação de agente, e IP ali é rotina."""
from __future__ import annotations

import ipaddress
import re

from ..models import Context, Finding
from . import files

IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3}))(?![\w]|\.\d)")
# o IP está "em uso": URL, porta, ssh/scp/ping/telnet, user@ip, ou palavra que o nomeia
IP_CONTEXT = re.compile(r"(?i)(?:https?://|ftp://|\bssh\b|\bscp\b|\bsftp\b|\bping\b|\btelnet\b|\bcurl\b|\bwget\b|\bhost\b|\bservidor\b|\bserver\b|\bip\b|\bendereco\b|\bendereço\b|@)\s*[^\s]{0,40}$")
PORT_AFTER = re.compile(r"^:\d{2,5}\b")
WELL_KNOWN = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "208.67.222.222", "208.67.220.220"}   # DNS públicos: não são da empresa

_LBL = r"[a-z0-9][a-z0-9-]{0,60}"      # rótulos e repetições limitados: sem backtracking explosivo (ver test_infra: entrada hostil)
INTERNAL_HOST = re.compile(rf"(?i)\b{_LBL}(?:\.{_LBL}){{0,5}}\.(?:internal|intranet|corp|lan|local|localdomain|intra|private)\b")   # só o final do nome: "smtp.interno.com" pode ser domínio público
USER_PATHS = (
    re.compile(r"(?i)\b[a-z]:\\users\\([^\\\s\"'<>|:*?]{2,40})\\"),
    re.compile(r"(?<![\w.])/home/([a-z0-9._-]{2,40})/"),
    re.compile(r"(?<![\w.])/Users/([A-Za-z0-9._-]{2,40})/"),
)
GENERIC_USERS = {"user", "users", "runner", "ubuntu", "ec2-user", "root", "admin", "administrator", "vagrant", "node", "app", "www-data", "default",
                 "public", "all users", "shared", "pi", "azureuser", "appuser", "circleci", "jenkins", "gitpod", "codespace", "vscode", "claude"}
# nome de arquivo mencionado no texto (a regra do nome é a mesma dos anexos)
FILE_TOKEN = re.compile(r"(?<![\w@])([\w.+-]{1,100}\.(?:pem|key|pfx|p12|ppk|kdbx|jks|keystore|tfstate|tfvars|sql|dump|bak|sqlite3?|mdb|xlsx?|docx?|pdf|csv|log))\b|(?<![\w])(\.env(?:\.[\w-]+)?)\b")
MENTION_CAP = 0.55   # citar um nome de arquivo no texto vale menos que anexá-lo
# Só nomes de documentos de negócio. Citar ".env", "id_rsa" ou "senhas.txt" não vaza segredo nenhum (é assunto comum de dev): não conta.
MENTION_CATEGORIES = ("rh", "financeiro", "juridico", "cliente", "estrategia_ma")


def _ip_ok(raw: str) -> ipaddress.IPv4Address | None:
    parts = raw.split(".")
    if any(len(p) > 1 and p.startswith("0") for p in parts):      # 010.001.... não é IP de verdade
        return None
    try:
        ip = ipaddress.IPv4Address(raw)
    except ValueError:
        return None
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved or raw in WELL_KNOWN or raw.startswith("255."):
        return None
    return ip


def detect(ctx: Context) -> list[Finding]:
    if ctx.kind in ("tool_call", "tool_result"):
        return []
    t, out = ctx.text, []
    for m in IPV4.finditer(t):
        ip = _ip_ok(m.group(1))
        if ip is None:
            continue
        before = t[max(0, m.start() - 48):m.start()]
        context = bool(IP_CONTEXT.search(before + "x")) or bool(PORT_AFTER.match(t[m.end():m.end() + 7])) or before.endswith("@")
        if ip.is_private or ip.is_link_local:
            conf, why = 0.75, "Endereço IP interno (rede privada)"
        elif context:
            conf, why = 0.7, "Endereço IP de servidor (em uso: URL, porta, ssh ou citado como servidor)"
        else:
            continue          # quatro números soltos (versão, medida) não bastam
        out.append(Finding("arquitetura", conf, why, "ip", m.start(1), m.end(1), "[IP]"))
    for m in INTERNAL_HOST.finditer(t):
        out.append(Finding("arquitetura", 0.7, "Nome de host interno da empresa", "internal_host", m.start(), m.end(), "[HOST]"))
    for rx in USER_PATHS:
        for m in rx.finditer(t):
            if m.group(1).lower() in GENERIC_USERS:
                continue
            out.append(Finding("pii", 0.5, "Nome de usuário em caminho de arquivo", "user_path", m.start(1), m.end(1), "[USUARIO]"))
    seen: set[str] = set()
    for m in FILE_TOKEN.finditer(t):
        token = (m.group(1) or m.group(2) or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        found, _ = files.detect_name(token)
        for f in found:
            if f.category in MENTION_CATEGORIES and f.span_type is None:
                out.append(Finding(f.category, min(f.confidence, MENTION_CAP), f"Arquivo citado no texto ({f.rule.split(': ', 1)[-1]})"))
    return out
