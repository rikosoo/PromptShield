"""Exportação para SIEM: Common Event Format (CEF versão 0) e envelope syslog.

Mapeamento de campos documentado em docs/siem.md. Regras de escape (fonte: guias de fornecedores que citam o
"ArcSight CEF Implementation Standard"; o PDF oficial não pôde ser aberto neste ambiente): no cabeçalho, `\\` e `|`
são escapados com barra invertida; na extensão, `\\` e `=` são escapados e quebras de linha viram `\\n`.
O texto do prompt NUNCA vai no CEF: só metadados e motivos do score.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

VENDOR, PRODUCT = "PromptShield", "PromptShield"
CEF_VERSION = "0"
_KEY = re.compile(r"^[A-Za-z0-9]+$")


def esc_header(v: str) -> str:
    return v.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def esc_ext(v: str) -> str:
    return v.replace("\\", "\\\\").replace("=", "\\=").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def cef_severity(score: int) -> int:
    """Escala CEF 0-10 a partir do score 0-100."""
    return max(0, min(10, round(score / 10)))


def build(version: str, signature_id: str, name: str, severity: int, ext: dict[str, Any]) -> str:
    for k in ext:
        if not _KEY.match(k):
            raise ValueError(f"chave de extensão inválida: {k!r}")
    header = "|".join(esc_header(str(x)) for x in (VENDOR, PRODUCT, version, signature_id, name, severity))
    body = " ".join(f"{k}={esc_ext(str(v))}" for k, v in ext.items() if v is not None and v != "")
    return f"CEF:{CEF_VERSION}|{header}|{body}"


def event_to_cef(row: dict[str, Any], version: str) -> str:
    """row: campos já mascarados do evento + análise (ver siem.event_record)."""
    cats = [c["id"] for c in row["categories"]]
    top = cats[0] if cats else "sem_categoria"
    rt = row["occurred_at"]
    if isinstance(rt, datetime):
        rt = int(rt.astimezone(timezone.utc).timestamp() * 1000)
    ext = {
        "rt": rt, "externalId": row["event_id"], "suser": row["user_id"], "act": row["decision"],
        "cat": top, "cn1": row["risk_score"], "cn1Label": "riskScore",
        "cs1": ",".join(cats), "cs1Label": "categories",
        "cs2": row["app"], "cs2Label": "app",
        "cs3": row.get("department") or "", "cs3Label": "department",
        "cs4": row["would_decide"], "cs4Label": "policyWouldDecide",
        "cs5": row["score_version"], "cs5Label": "scoreVersion",
        "cs6": row["channel"], "cs6Label": "channel",
        "msg": "; ".join(f"{r['rule']} (+{r['contribution']})" for r in row["reasons"]),
    }
    return build(version, top, row["title"], cef_severity(row["risk_score"]), ext)


def syslog_5424(msg: str, hostname: str = "promptshield", pri: int = 14, when: datetime | None = None) -> str:
    """Envelope RFC 5424 (VERSION 1, sem dados estruturados). pri 14 = facility user(1) x 8 + severity informational(6)."""
    ts = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return f"<{pri}>1 {ts} {hostname} promptshield - - - {msg}"
