"""analyze(event) -> Analysis. Biblioteca pura: sem rede, sem banco, sem LLM externo."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .detectors import agent, business, code, declared, files, infra, injection, pii, secrets
from .detectors.injection import InjectionClassifier
from .intents import detect_intents
from .masking import apply_masks
from .models import KINDS, Analysis, Context, Finding, Span
from .ner import NerDetector
from .scoring import ALERT_LEVEL, ENGINE_VERSION, SCORE_VERSION, THRESHOLD, score, severity_for
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
        return "alert"     # o PromptShield é PASSIVO: o motor nunca sugere bloqueio, só alerta
    if ids & MASKING:
        return "mask"
    if ids & ALERTING:
        return "alert"
    return "allow"


def analyze(event: Mapping[str, Any], *, allowed_hosts: tuple[str, ...] = (),
            project_names: tuple[str, ...] = (), classifier: InjectionClassifier | None = None,
            taxonomy: dict[str, Category] | None = None, ner: NerDetector | None = None,
            weights: Mapping[str, int] | None = None) -> Analysis:
    """`weights`: peso (0 a 100) por categoria, definido pela empresa; o que faltar usa o peso padrão da taxonomia."""
    cats = taxonomy or load()
    ctx = context_from_event(event, allowed_hosts, project_names)
    findings: list[Finding] = []
    findings += pii.detect(ctx)
    findings += secrets.detect(ctx)
    findings += declared.detect(ctx)
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

    declared_spans = [(f.start, f.end) for f in findings if f.span_type == "declared_token" and f.start is not None]
    findings = [f for f in findings if not (f.span_type == "high_entropy" and f.start is not None       # o detector antigo vazaria 2 caracteres ("76****")
                                            and any(a < f.end and f.start < b for a, b in declared_spans))]
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
    has_code = code.has_code(ctx.text)
    sc, reasons = score(reported, cats, ctx.kind == "tool_call", ctx.personal_account, findings=findings, weights=weights,
                        has_code=has_code, external_url=agent.has_external_url(ctx))
    spans = [Span(f.start, f.end, f.span_type or "", f.masked or "[oculto]")
             for f in findings if f.start is not None and f.end is not None
             and f.confidence >= THRESHOLD and f.span_type not in ("shell", "file")]
    seen: set[tuple[int, int]] = set()
    spans = [sp for sp in spans if not ((sp.start, sp.end) in seen or seen.add((sp.start, sp.end)))]
    spans += _repeat_spans(ctx.text, spans)
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
        findings=_finding_rows(findings, spans),
        severity=severity_for(sc),
        alert_level=ALERT_LEVEL[severity_for(sc)],
        engine_version=ENGINE_VERSION,
    )


SECRET_VALUE_SPANS = {"declared_token", "password", "high_entropy", "bearer_token", "private_key_body"}


def _repeat_spans(text: str, spans: list[Span]) -> list[Span]:
    """O mesmo valor secreto citado de novo em outro ponto do texto também é mascarado (senão só a primeira ocorrência sumia)."""
    extra: list[Span] = []
    taken = [(s.start, s.end) for s in spans]
    for sp in spans:
        value = text[sp.start:sp.end]
        if sp.type not in SECRET_VALUE_SPANS or len(value) < 8:
            continue
        i = text.find(value)
        while i != -1:
            if not any(a < i + len(value) and i < b for a, b in taken):
                extra.append(Span(i, i + len(value), sp.type, sp.masked))
                taken.append((i, i + len(value)))
            i = text.find(value, i + len(value))
    return extra


def _finding_rows(findings: list[Finding], spans: list[Span]) -> list[dict[str, Any]]:
    """Achados que contam (confiança >= limiar), sem repetir tipo+categoria. A evidência é SEMPRE a máscara, nunca o valor."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for f in findings:
        if f.confidence < THRESHOLD:
            continue
        kind = f.span_type or f.category
        key = (kind, f.category)
        if key not in out or f.confidence > out[key]["confidence"]:
            out[key] = {"type": kind, "category": f.category, "confidence": round(f.confidence, 2), "rule": f.rule, "evidence": f.masked}
    return sorted(out.values(), key=lambda r: (-r["confidence"], r["type"]))
