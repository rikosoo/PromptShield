"""analyze(event) -> Analysis. Biblioteca pura: sem rede, sem banco, sem LLM externo."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .detectors import agent, business, code, files, infra, injection, pii, secrets
from .detectors.injection import InjectionClassifier
from .intents import detect_intents
from .masking import apply_masks
from .models import KINDS, Analysis, Context, Finding, Span
from .ner import NerDetector
from .scoring import SCORE_VERSION, THRESHOLD, score
from .taxonomy import Category, load

BLOCKING = {"segredo", "shell_destrutivo", "leitura_env", "exfiltracao_ferramenta", "envenenamento_mcp"}
MASKING = {"pii", "financeiro"}
ALERTING = {"injection_direta", "injection_indireta", "jailbreak", "extracao_system_prompt"}


def context_from_event(event: Mapping[str, Any], allowed_hosts: tuple[str, ...] = (),
                       project_names: tuple[str, ...] = ()) -> Context:
    content = event.get("content") or {}
    kind = event.get("kind", "prompt")
    if kind not in KINDS:
        raise ValueError(f"kind inválido: {kind!r}")
    tool_input = content.get("tool_input")
    text = content.get("text") or ""
    if not text and isinstance(tool_input, dict):
        text = str(tool_input.get("command") or "")
    return Context(
        text=text, kind=kind, tool_name=content.get("tool_name"),
        tool_input=tool_input if isinstance(tool_input, dict) else None,
        personal_account=bool((event.get("context") or {}).get("personal_account", False)),
        allowed_hosts=allowed_hosts, project_names=project_names,
        attachments=tuple(a for a in (content.get("attachments") or ()) if isinstance(a, Mapping)),
    )


def _default_decision(ids: set[str]) -> str:
    """Decisão sugerida só para o motor. A política do tenant (Etapa 3) é quem decide de fato."""
    if ids & BLOCKING:
        return "block"
    if ids & MASKING:
        return "mask"
    if ids & ALERTING:
        return "alert"
    return "allow"


def analyze(event: Mapping[str, Any], *, allowed_hosts: tuple[str, ...] = (),
            project_names: tuple[str, ...] = (), classifier: InjectionClassifier | None = None,
            taxonomy: dict[str, Category] | None = None, ner: NerDetector | None = None) -> Analysis:
    cats = taxonomy or load()
    ctx = context_from_event(event, allowed_hosts, project_names)
    findings: list[Finding] = []
    findings += pii.detect(ctx)
    findings += secrets.detect(ctx)
    findings += code.detect(ctx)
    findings += injection.detect(ctx, classifier)
    findings += agent.detect(ctx)
    findings += business.detect(ctx)
    findings += infra.detect(ctx)
    if ner is not None:
        findings += ner.detect(ctx)
    file_findings, attachments = files.detect(ctx.attachments)
    findings += file_findings    # sem posição no texto: contam como categoria e risco, não como trecho a mascarar

    conn = [(f.start, f.end) for f in findings if f.span_type == "conn_string"]
    findings = [f for f in findings if not (       # o host dentro de uma string de conexão já sai mascarado junto com o segredo
        f.span_type in ("ip", "internal_host") and any(a <= f.start < b for a, b in conn))]
    if any(f.category == "exfiltracao_ferramenta" and f.confidence >= THRESHOLD for f in findings):
        findings = [f for f in findings if f.span_type != "ip"]        # o IP de destino de um envio de dados é evidência do ataque, não da infraestrutura da empresa
    ip_tail = re.compile(r"@\d{1,3}(?:\.\d{1,3}){3}$")     # usuario@10.0.0.5 (ssh/scp) não é e-mail: o IP é tratado à parte
    findings = [f for f in findings if not (
        f.span_type == "email" and (ctx.kind == "tool_call" or any(a <= f.start < b for a, b in conn)
                                    or ip_tail.search(ctx.text[f.start:f.end])))]

    best: dict[str, Finding] = {}
    for f in findings:
        if f.category not in cats:
            raise ValueError(f"categoria fora da taxonomia: {f.category}")
        if f.category not in best or f.confidence > best[f.category].confidence:
            best[f.category] = f
    reported = {c: f for c, f in best.items() if f.confidence >= THRESHOLD}
    if not reported and business.productive(ctx):
        reported["produtividade_legitima"] = Finding("produtividade_legitima", 0.6, "Tarefa de trabalho comum")
        best["produtividade_legitima"] = reported["produtividade_legitima"]

    is_agent = ctx.kind == "tool_call" or any(c in reported for c in cats if cats[c].grupo == "Ações de agente")
    sc, reasons = score(reported, cats, ctx.kind == "tool_call", ctx.personal_account)
    spans = [Span(f.start, f.end, f.span_type or "", f.masked or "[oculto]")
             for f in findings if f.start is not None and f.end is not None
             and f.confidence >= THRESHOLD and f.span_type not in ("shell", "file")]
    seen: set[tuple[int, int]] = set()
    spans = [sp for sp in spans if not ((sp.start, sp.end) in seen or seen.add((sp.start, sp.end)))]
    sensitive = any(cats[c].grupo == "Dados sensíveis" for c in reported)
    ids = set(reported)
    return Analysis(
        categories=[{"id": c, "confidence": round(f.confidence, 2)}
                    for c, f in sorted(reported.items(), key=lambda kv: (-kv[1].confidence, kv[0]))],
        flags={"has_code": code.has_code(ctx.text), "has_sensitive": sensitive, "is_agent_action": is_agent,
               "intents": detect_intents(ctx), "has_attachments": bool(attachments)},
        risk={"score": sc, "reasons": [{"rule": r.rule, "contribution": r.contribution,
                                         **({"category": r.category} if r.category else {})} for r in reasons]},
        spans=spans,
        decision=_default_decision(ids),
        masked_text=apply_masks(ctx.text, spans),
        attachments=attachments,
        score_version=SCORE_VERSION,
    )
