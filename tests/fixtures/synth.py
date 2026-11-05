"""Expande marcadores @@tipo:N@@ em valores sintéticos com formato de credencial.

Os valores NÃO ficam no repositório (o scanner de segredos do GitHub os reconheceria): o arquivo
examples.jsonl guarda só o marcador, e esta função gera o valor, de forma determinística, ao carregar.
"""
from __future__ import annotations

import random
import re
import string

_MARK = re.compile(r"@@(\w+):(\d+)@@")
_AN = string.ascii_letters + string.digits
_UP = string.ascii_uppercase + string.digits


def _s(r: random.Random, n: int, chars: str = _AN) -> str:
    return "".join(r.choice(chars) for _ in range(n))


def make(kind: str, n: int) -> str:
    r = random.Random(f"{kind}:{n}")
    if kind == "aws":
        return "AKIA" + _s(r, 16, _UP)
    if kind == "ghp":
        return "ghp_" + _s(r, 36)
    if kind == "slack":
        return f"xoxb-{r.randint(10**9, 10**10 - 1)}-{r.randint(10**9, 10**10 - 1)}-{_s(r, 24)}"
    if kind == "stripe":
        return "sk_live_" + _s(r, 24)
    if kind == "gcp":
        return "AIza" + _s(r, 35, _AN + "_-")
    if kind == "jwt":
        return f"eyJ{_s(r, 20)}.eyJ{_s(r, 30)}.{_s(r, 30)}"
    if kind == "pem":
        return "-----BEGIN RSA PRIVATE KEY-----\n" + _s(r, 60) + "\n" + _s(r, 60) + "\n-----END RSA PRIVATE KEY-----"
    if kind == "azure":
        return "AccountKey=" + _s(r, 86, _AN + "+/") + "=="
    if kind == "awssecret":
        return _s(r, 40, _AN + "/+")
    if kind == "openai":
        return "sk-proj-" + _s(r, 48, _AN + "_-")
    if kind == "anthropic":
        return "sk-ant-api03-" + _s(r, 64, _AN + "_-")
    if kind == "npm":
        return "npm_" + _s(r, 36)
    if kind == "gitlab":
        return "glpat-" + _s(r, 20, _AN + "_-")
    if kind == "sendgrid":
        return "SG." + _s(r, 22, _AN + "_-") + "." + _s(r, 43, _AN + "_-")
    if kind == "hf":
        return "hf_" + _s(r, 34)
    if kind == "pypi":
        return "pypi-AgEIcHlwaS5vcmc" + _s(r, 60, _AN + "_-")
    if kind == "dopat":
        return "dop_v1_" + _s(r, 64, "0123456789abcdef")
    if kind == "slackhook":
        return "https://hooks.slack.com/services/T" + _s(r, 10, _UP) + "/B" + _s(r, 10, _UP) + "/" + _s(r, 24)
    if kind == "awsdoc":   # a chave de EXEMPLO da documentação da AWS (pública): montada na hora para não aparecer em arquivo
        return "AKIA" + "IOSFODNN7" + "EXAMPLE"
    if kind == "pwd":
        return _s(r, 12, _AN + "!@#$%")
    raise ValueError(kind)


def render(text: str) -> str:
    return _MARK.sub(lambda m: make(m.group(1), int(m.group(2))), text)
