"""Arquivos anexados: SÓ o nome (e tamanho/tipo) é avaliado. O conteúdo do arquivo nunca é lido nem enviado.

Limite honesto: o nome sugere, não prova. `senhas.txt` pode estar vazio e `relatorio.pdf` pode ter segredo. É um sinal de risco, não um veredito.
"""
from __future__ import annotations

import re
from typing import Any

from ..masking import apply_masks
from ..models import Context, Finding, Span
from ..textnorm import fold
from . import pii, secrets

# (categoria, confiança, expressão sobre o nome em minúsculas e sem acento, descrição)
RULES: tuple[tuple[str, float, re.Pattern[str], str], ...] = (
    ("segredo", 0.9, re.compile(r"(^|/)\.env(\.|$)|(^|[^a-z])(id_rsa|id_ed25519|id_ecdsa)|\.(pem|key|pfx|p12|ppk|kdbx|keystore|jks|tfstate|tfvars)$"), "arquivo de chave/credencial"),
    ("segredo", 0.75, re.compile(r"credential|credencia|secret|segredo|senhas?([^a-z]|$)|passwords?([^a-z]|$)|\btoken"), "nome sugere senha ou credencial"),
    ("sql", 0.6, re.compile(r"\.(sql|dump|bak|sqlite3?|db|mdb)$|backup"), "dump ou backup de banco"),
    ("rh", 0.7, re.compile(r"folha[ _.-]*(de[ _.-]*)?pagamento|holerite|contracheque|salari|avaliacao[ _.-]*(de[ _.-]*)?desempenho|demissao|rescisao"), "nome sugere dado de RH"),
    ("financeiro", 0.6, re.compile(r"extrato|balancete|balanco|faturamento|fluxo[ _.-]*de[ _.-]*caixa|\bdre\b"), "nome sugere dado financeiro"),
    ("juridico", 0.6, re.compile(r"contrato|procuracao|confidencialidade|\bnda\b|acordo[ _.-]*(de|judicial)|processo[ _.-]*n"), "nome sugere documento jurídico"),
    ("cliente", 0.6, re.compile(r"clientes?([^a-z]|$)|leads?([^a-z]|$)|base[ _.-]*de[ _.-]*(clientes|contatos)|contatos"), "nome sugere base de clientes"),
    ("estrategia_ma", 0.6, re.compile(r"due[ _.-]*diligence|term[ _.-]*sheet|fusao|aquisicao|m&a|\bm_a\b"), "nome sugere M&A"),
    ("logs", 0.5, re.compile(r"\.log$|\.log\.\d+$"), "arquivo de log"),
    ("codigo_proprietario", 0.5, re.compile(r"(codigo[ _.-]*fonte|source|\bsrc\b|repo|fontes)[^/]*\.(zip|tar|tgz|gz|7z|rar)$|\.(zip|tar|tgz|7z|rar)$.*(src|fonte)"), "pacote que parece código-fonte"),
)


def _clean(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1][:255]   # só o nome, sem pasta (o caminho pode ter o nome de usuário)


def detect_name(name: str) -> tuple[list[Finding], str]:
    """Achados do nome de um arquivo e o nome já mascarado (e-mail, CPF etc. dentro do nome não ficam no banco)."""
    name = _clean(name)
    low = fold(name)
    out = [Finding(cat, conf, f"arquivo anexado: {why}", None) for cat, conf, rx, why in RULES if rx.search(low)]
    ctx = Context(text=name, kind="prompt")
    inner = [f for f in pii.detect(ctx) + secrets.detect(ctx) if f.confidence >= 0.5]
    spans = [Span(f.start, f.end, f.span_type or "", f.masked or "[oculto]") for f in inner if f.start is not None and f.end is not None]
    out += [Finding(f.category, f.confidence, f"arquivo anexado: {f.rule}") for f in inner]
    return out, apply_masks(name, spans)


def detect(attachments: tuple[dict[str, Any], ...]) -> tuple[list[Finding], list[dict[str, Any]]]:
    findings: list[Finding] = []
    shown: list[dict[str, Any]] = []
    for a in attachments[:20]:
        name = str(a.get("name") or "").strip()
        if not name:
            continue
        fs, masked = detect_name(name)
        findings += fs
        shown.append({"name": masked, "size": a.get("size") if isinstance(a.get("size"), int) else None, "mime": (a.get("mime") or None) and str(a["mime"])[:100]})
    return findings, shown
