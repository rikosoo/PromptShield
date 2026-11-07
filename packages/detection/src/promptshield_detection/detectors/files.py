"""Arquivos anexados: SÓ o nome, a extensão, o tipo e o tamanho são avaliados e guardados. O conteúdo do arquivo nunca é lido nem enviado.

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
    # --- financeiro (nome) ---
    ("financeiro", 0.65, re.compile(r"nota[ _.-]*fiscal|(^|[^a-z])(nf-?e|nfe|nfse|danfe)([^a-z]|$)|boleto|fatura|invoice|duplicata|orcamento|budget|comprovante|conciliacao|contas?[ _.-]*a[ _.-]*(pagar|receber)|cobranca|inadimpl|payroll|cnab"), "nome sugere documento financeiro"),
    ("financeiro", 0.7, re.compile(r"imposto[ _.-]*de[ _.-]*renda|irpf|(^|[^a-z])(dirf|darf|sped|ecf|ecd)([^a-z]|$)|extrato[ _.-]*banc|informe[ _.-]*de[ _.-]*rendimentos"), "nome sugere declaração fiscal ou extrato"),
    # --- dados pessoais (nome) ---
    ("pii", 0.7, re.compile(r"(^|[^a-z])(cpf|rg|cnh|ctps|cv)([^a-z]|$)|passaporte|passport|certidao|comprovante[ _.-]*de[ _.-]*residencia|curriculo|ficha[ _.-]*cadastral|dados[ _.-]*pessoais|documento[ _.-]*de[ _.-]*identidade|titulo[ _.-]*de[ _.-]*eleitor|carteira[ _.-]*de[ _.-]*trabalho"), "nome sugere documento pessoal"),
    # --- saúde (nome) ---
    ("saude", 0.75, re.compile(r"atestado|laudo|(^|[^a-z])exames?([^a-z]|$)|prontuario|receita[ _.-]*medica|hemograma|ressonancia|tomografia|biopsia|cid[ _.-]?10|medical[ _.-]*record|carteira[ _.-]*de[ _.-]*vacina"), "nome sugere dado de saúde"),
    # --- mais RH, segredos, infraestrutura e propriedade intelectual (nome) ---
    ("rh", 0.65, re.compile(r"admissao|contrato[ _.-]*de[ _.-]*trabalho|advertencia|fgts|esocial|(^|[^a-z])(rais|pdi)([^a-z]|$)|ficha[ _.-]*de[ _.-]*funcionario"), "nome sugere documento de RH"),
    ("segredo", 0.85, re.compile(r"(^|/)\.(npmrc|netrc|pgpass|git-credentials|htpasswd|pypirc)$|kubeconfig|wallet\.dat|seed[ _.-]*phrase|mnemonic|frase[ _.-]*de[ _.-]*recuperacao|service[ _.-]*account.*\.json$"), "arquivo de credencial ou carteira"),
    ("arquitetura", 0.6, re.compile(r"arquitetura|topologia|network[ _.-]*diagram|diagrama[ _.-]*de[ _.-]*(rede|infra)"), "nome sugere arquitetura ou rede"),
    ("propriedade_intelectual", 0.55, re.compile(r"patente|patent|segredo[ _.-]*industrial|trade[ _.-]*secret"), "nome sugere propriedade intelectual"),
    ("codigo_proprietario", 0.5, re.compile(r"(codigo[ _.-]*fonte|source|\bsrc\b|repo|fontes)[^/]*\.(zip|tar|tgz|gz|7z|rar)$|\.(zip|tar|tgz|7z|rar)$.*(src|fonte)"), "pacote que parece código-fonte"),
)


CODE_EXT = frozenset("py js jsx mjs ts tsx java kt kts go rs c h cpp cc hpp cs rb php swift scala lua pl dart vue svelte ipynb sh bash ps1 bat cmd".split())
IAC_EXT = frozenset("tf hcl bicep".split())
DATA_EXT = frozenset("csv tsv xls xlsx xlsm ods numbers parquet jsonl sql dump bak sqlite sqlite3 db mdb".split())
BANK_EXT = frozenset("ofx qif ofc sped".split())
MAIL_EXT = frozenset("eml msg pst ost mbox".split())
CAPTURE_EXT = {"har": ("segredo", 0.6, "captura de navegador (HAR) costuma conter tokens e cookies"),
               "dmp": ("segredo", 0.6, "despejo de memória pode conter senhas e tokens"),
               "hprof": ("segredo", 0.6, "despejo de memória pode conter senhas e tokens"),
               "pcap": ("logs", 0.6, "captura de rede pode conter credenciais e hosts internos"),
               "pcapng": ("logs", 0.6, "captura de rede pode conter credenciais e hosts internos")}
MIME_EXT = {"text/csv": "csv", "text/tab-separated-values": "tsv", "application/vnd.ms-excel": "xls", "application/sql": "sql",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "application/x-ofx": "ofx",
            "text/x-python": "py", "text/javascript": "js", "application/javascript": "js", "text/x-java-source": "java",
            "application/x-sh": "sh", "application/x-sqlite3": "sqlite", "message/rfc822": "eml"}
CODE_BIG_BYTES = 100 * 1024    # arquivo de código de 100 KB ou mais: muito código de uma vez
BULK_BYTES = 5 * 1024 * 1024    # planilha, dump ou banco a partir de 5 MB: o volume sugere uma base de registros, não um exemplo


def _ext(low: str, mime: str | None) -> str:
    base = low.rsplit("/", 1)[-1]
    if base.startswith(("dockerfile", "docker-compose")):
        return "dockerfile"
    ext = base.rsplit(".", 1)[-1] if "." in base.strip(".") else ""
    if ext.isalnum() and len(ext) <= 8:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "")


def _by_type(ext: str, size: int | None) -> list[Finding]:
    """Sinais pela EXTENSÃO/TIPO e pelo TAMANHO. Fracos de propósito: o conteúdo do arquivo nunca é lido."""
    out: list[Finding] = []
    if ext in CODE_EXT:
        big = size is not None and size >= CODE_BIG_BYTES
        out.append(Finding("codigo_proprietario", 0.8 if big else 0.6,
                           "arquivo anexado: arquivo de código-fonte" + (f" grande ({size // 1024} KB)" if big else "")))
    if ext in IAC_EXT or ext == "dockerfile":
        out.append(Finding("iac", 0.7, "arquivo anexado: infraestrutura como código"))
    if ext in BANK_EXT:
        out.append(Finding("financeiro", 0.85, "arquivo anexado: formato de extrato bancário ou fiscal"))
    if ext in MAIL_EXT:
        out.append(Finding("cliente", 0.5, "arquivo anexado: caixa de e-mails (conversas externas, dados de clientes e pessoais)"))
    if ext in CAPTURE_EXT:
        cat, conf, why = CAPTURE_EXT[ext]
        out.append(Finding(cat, conf, f"arquivo anexado: {why}"))
    if ext in DATA_EXT and size is not None and size >= BULK_BYTES:
        out.append(Finding("cliente", 0.5, f"arquivo anexado: planilha, dump ou banco de {size // (1024 * 1024)} MB (volume sugere base de registros)"))
    return out


def _clean(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1][:255]   # só o nome, sem pasta (o caminho pode ter o nome de usuário)


def detect_name(name: str, size: int | None = None, mime: str | None = None) -> tuple[list[Finding], str]:
    """Achados do nome de um arquivo e o nome já mascarado (e-mail, CPF etc. dentro do nome não ficam no banco)."""
    name = _clean(name)
    low = fold(name)
    out = [Finding(cat, conf, f"arquivo anexado: {why}", None) for cat, conf, rx, why in RULES if rx.search(low)]
    out += _by_type(_ext(low, mime), size)
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
        size = a.get("size") if isinstance(a.get("size"), int) and not isinstance(a.get("size"), bool) and a["size"] >= 0 else None
        mime = (a.get("mime") or None) and str(a["mime"])[:100]
        fs, masked = detect_name(name, size, mime)
        findings += fs
        shown.append({"name": masked, "size": size, "mime": mime})
    return findings, shown
