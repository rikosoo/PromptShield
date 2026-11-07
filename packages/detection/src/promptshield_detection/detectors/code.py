"""Código e engenharia: presença/linguagem de código, IaC, SQL, logs, arquitetura, revisão."""
from __future__ import annotations

import re

from ..models import Context, Finding

FENCE = re.compile(r"```")
LANG_SIGNALS: dict[str, re.Pattern[str]] = {
    "python": re.compile(r"^\s*(?:def \w+\(|class \w+[:(]|import \w+|from \w+ import |if __name__|(?<=\s)return\b|for \w+ in [^\n]+:\s*$|while [^\n]+:\s*$|print\(|try:\s*$|except\b[^\n]*:\s*$|with [^\n]+ as \w+:\s*$)", re.M),
    "javascript": re.compile(r"\b(?:function \w+\(|const \w+ =|let \w+ =|=> \{|console\.log|require\()"),
    "typescript": re.compile(r"\b(?:interface \w+ \{|: (?:string|number|boolean)\b|export (?:const|function|type))"),
    "java": re.compile(r"\b(?:public (?:static )?(?:class|void)|System\.out\.println|import java\.)"),
    "go": re.compile(r"^\s*(?:package \w+|func \w+\(|import \()", re.M),
    "c": re.compile(r"#include\s*<|\bint main\s*\(|\b(?:void|int|float|double|char|bool)\s+\*?\w+\s*\([^)]*\)\s*\{"),
    "rust": re.compile(r"^\s*(?:fn \w+\s*[(<]|use std::|impl(?:<[^>]*>)? \w+|let mut \w+|pub (?:fn|struct|enum) \w+)", re.M),
    "php": re.compile(r"<\?php|\$this->\w+|^\s*(?:namespace \w+(?:\\\w+)*;|use \w+(?:\\\w+)+;)", re.M),
    "ruby": re.compile(r"^\s*(?:def \w+[^\n]*\n|class \w+ < \w+|require ['\"]|attr_(?:accessor|reader)|module \w+\s*$)", re.M),
    "csharp": re.compile(r"\b(?:using System\w*(?:\.\w+)*;|Console\.WriteLine|namespace \w+(?:\.\w+)*\s*\{?|public (?:async )?(?:Task|void|string|int) \w+\()"),
    "kotlin": re.compile(r"^\s*(?:fun \w+\(|data class \w+|val \w+(?:: \w+)? =|override fun \w+)", re.M),
    "swift": re.compile(r"^\s*(?:func \w+\(|import (?:UIKit|SwiftUI|Foundation)|guard let \w+|struct \w+: \w+)", re.M),
    "shell": re.compile(r"^#!/bin/(?:ba)?sh|^\s*(?:export \w+=|if \[ )", re.M),
}
# comandos de PowerShell/shell colados no texto: contam como "tem código" (não como linguagem, para não puxar o cabeçalho proprietário)
SHELL_CMD = re.compile(
    r"(?i)\b(?:Invoke-(?:WebRequest|RestMethod|Expression)|iwr|irm|iex|Expand-Archive|Select-String|Get-(?:ChildItem|Content|Item|Process|Service)|Set-(?:Content|ExecutionPolicy)|New-Item|Remove-Item)\b"
    r"|\$env:\w+|(?m:^\s*(?:sudo|curl|wget|ssh|scp|chmod|chown|docker|kubectl|apt(?:-get)?|systemctl)\s+\S)")
SQL_RE = re.compile(
    r"(?i)\b(?:select\s+[\w*,.\s()'\"`]+?\s+from\s+\w+|insert\s+into\s+\w+|update\s+\w+\s+set\s+\w+\s*=|"
    r"delete\s+from\s+\w+|create\s+table\s+\w+|drop\s+table\s+\w+|alter\s+table\s+\w+)")
IAC_RES = [
    re.compile(r'(?m)^\s*(?:resource|module|provider|variable|data)\s+"[\w-]+"(?:\s+"[\w-]+")?\s*\{'),
    re.compile(r"(?m)^apiVersion:\s*\S+\s*\n(?:.*\n)*?kind:\s*\w+"),
    re.compile(r"(?m)^FROM\s+\S+.*\n(?:.*\n)*?(?:RUN|COPY|CMD|ENTRYPOINT)\s"),
    re.compile(r"(?m)^\s*-\s+(?:name|hosts):\s*.+\n(?:.*\n)*?\s+(?:apt|yum|ansible\.builtin\.\w+|become):"),
    re.compile(r"(?m)^AWSTemplateFormatVersion:"),
    re.compile(r"(?i)\bterraform\s+(?:apply|plan|destroy|init)\b|\baws_[a-z0-9_]+\.[\w-]+|\bkubectl\s+(?:apply|rollout)\b"),
]
COMMAND_IAC = 5   # índice da expressão acima: comando solto (não é arquivo de configuração); ignorada em chamadas de ferramenta
TRACE_RES = [
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"(?m)^\s+at [\w$.<>]+\([\w.]+:\d+\)"),
    re.compile(r"Exception in thread|Caused by: [\w.]+"),
    re.compile(r"(?m)^\w*(?:Error|Exception): .+\n\s+at "),
]
LOG_LINE = re.compile(r"(?m)^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\n]{0,30}?\b(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\b")
PRIV_IP = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")
ARCH_TERMS = re.compile(
    r"(?i)diagrama de arquitetura|arquitetura interna|topologia de rede|internal architecture|"
    r"network topology|\bVPC\b|\bCIDR\b|service mesh interno|bastion|subnet")
ARCH_PARTS = re.compile(r"(?i)\b(?:api gateway|gateway|microsservi\w+|microservices?|kafka|rabbitmq|aurora|rds|vpcs?|transit gateway|direct connect|subnets?|bastion|vault|"
                        r"load balancer|balanceador|peered|peering|on-prem\w*|worker|fila|queue|topico|topic|cluster|replicas?|read replica|service mesh|vpn|firewall|dmz|kubernetes|k8s)\b")
ARCH_OWN = re.compile(r"(?i)\b(?:nosso|nossa|nossos|nossas|our|internal|interno|interna|topologia|topology|desenho|nossa arquitetura|our architecture)\b")
REVIEW_PHRASES = re.compile(
    r"(?i)\b(?:revis[ea]r?|revisa|review|o ?que (?:(?:voce|você|vc|tu) )?acha|what do you think|pull request|code review|tem bug|has a bug|me diz se|look at this|check this|what'?s wrong|o que (?:ta|esta) errado|olha (?:esse|este)|refator\w*|refactor|debug\w*|depur\w*|find the bug|ache o bug|"
    r"por que (?:este|esse) c[óo]digo|why (?:does|is) this (?:code|function))\b")
OPEN_LICENSE = re.compile(r"(?i)SPDX-License-Identifier:\s*(?:MIT|Apache-2\.0|BSD|ISC|GPL|LGPL|MPL)|\b(?:MIT|Apache) License\b")
PROPRIETARY = re.compile(
    r"(?i)copyright\s*(?:\(c\)|©)?\s*\d{4}[^\n]{0,60}(?:ltda|s\.a\.|inc\.?|corp|gmbh)|proprietary|"
    r"confidential|confidencial|uso interno|internal use only|todos os direitos reservados|all rights reserved|"
    r"do not distribute|not for distribution|n[aã]o distribuir|trade secret|segredo industrial|uso restrito")
INTERNAL_PATH = re.compile(r"(?:/|\\)(?:internal|src/internal|corp|intranet)(?:/|\\)|\.corp\.|\.internal\b|\.local\b")


DIFF_RE = re.compile(r"diff --git a/\S+ b/\S+|@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@|(?m:^--- a/\S+)|(?m:^\+\+\+ b/\S+)")


def code_presence(text: str) -> tuple[bool, str | None]:
    if len(DIFF_RE.findall(text)) >= 2:
        return True, "diff"
    fenced = len(FENCE.findall(text)) >= 2
    best, best_n = None, 0
    for lang, rx in LANG_SIGNALS.items():
        n = len(rx.findall(text))
        if n > best_n:
            best, best_n = lang, n
    structural = len(re.findall(r"[{};]\s*$", text, re.M)) >= 3
    shellish = len(SHELL_CMD.findall(text)) >= 2
    return (fenced or best_n >= 2 or (best_n >= 1 and structural) or shellish), best


def has_code(text: str) -> bool:
    return code_presence(text)[0]


def detect(ctx: Context) -> list[Finding]:
    t, out = ctx.text, []
    is_code, lang = code_presence(t)
    if SQL_RE.search(t) and not re.search(r"(?i)^\s*(?:quero|want to|i want)\b", t):
        out.append(Finding("sql", 0.75, "Instrução SQL"))
    rules = IAC_RES[:COMMAND_IAC] if ctx.kind == "tool_call" else IAC_RES
    if any(rx.search(t) for rx in rules):
        out.append(Finding("iac", 0.8, "Infraestrutura como código (Terraform, Kubernetes, Docker ou Ansible)"))
    traces = sum(1 for rx in TRACE_RES if rx.search(t))
    if traces or len(LOG_LINE.findall(t)) >= 2:
        out.append(Finding("logs", 0.8 if traces else 0.7, "Stack trace ou linhas de log"))
    ips = set(PRIV_IP.findall(t))
    parts = {m.group(0).lower() for m in ARCH_PARTS.finditer(t)}
    if len(parts) >= 3 and ARCH_OWN.search(t):
        out.append(Finding("arquitetura", 0.65, "Descrição da arquitetura/rede da própria empresa", ))
    if ARCH_TERMS.search(t) and (len(ips) >= 1 or re.search(r"(?i)arquitetura interna|internal architecture", t)):
        out.append(Finding("arquitetura", 0.7, "Termos de arquitetura com IPs privados"))
    if is_code and REVIEW_PHRASES.search(t):
        out.append(Finding("revisao_codigo", 0.7, "Código com pedido de revisão ou depuração"))
    weak_code = lang is not None   # um único sinal de linguagem (ex.: uma classe Java em uma linha) já basta para o cabeçalho proprietário
    if (is_code or weak_code) and not OPEN_LICENSE.search(t):
        names = [n for n in ctx.project_names if n and n.lower() in t.lower()]
        if PROPRIETARY.search(t) or INTERNAL_PATH.search(t) or names:
            out.append(Finding("codigo_proprietario", 0.75,
                               "Código com cabeçalho proprietário, caminho interno ou nome de projeto"))
    return out
