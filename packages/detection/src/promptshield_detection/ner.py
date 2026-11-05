"""Nomes de pessoas via Microsoft Presidio + spaCy (opcional, roda 100% local).

Instalação: `pip install "promptshield-detection[ner]"` e os modelos do spaCy
(`pt_core_news_sm`, `en_core_web_sm`) a partir dos releases oficiais do spaCy.
Só nomes completos (2 ou mais palavras) contam como PII; nome solto fica abaixo do limiar.
Cidades e países não são PII por si só e não são reportados.
"""
from __future__ import annotations

import re

from .models import Context, Finding

_ORG = re.compile(r"(?i)\b(?:ltda|s\.?a\.?|inc|corp|llc|eireli|empresa|company|foundation|funda[çc][ãa]o)\b")
_ORG_AFTER = re.compile(r"^[\s,.]*(?:ltda|s\.?a\.?|inc|corp|llc|eireli|me|epp)\b", re.I)
_COPYRIGHT_BEFORE = re.compile(r"(?i)(?:copyright|\(c\)|©)[^\n]{0,15}$")
_PT_HINT = re.compile(r"[ãõçáéíóúâêô]|\b(?:de|da|do|para|com|que|uma?|os|as|não|ligue|falar|cliente)\b", re.I)


class NerUnavailableError(RuntimeError):
    pass


class NerDetector:
    def __init__(self, models: dict[str, str] | None = None) -> None:
        models = models or {"pt": "pt_core_news_sm", "en": "en_core_web_sm"}
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            nlp = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": k, "model_name": v} for k, v in models.items()],
            }).create_engine()
            self._engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=list(models))
        except Exception as exc:  # modelo ou pacote ausente
            raise NerUnavailableError(
                "Presidio/spaCy indisponível. Instale o extra [ner] e os modelos do spaCy. Detalhe: " + str(exc)
            ) from exc
        self._langs = set(models)

    def detect(self, ctx: Context) -> list[Finding]:
        if ctx.kind == "tool_call" or not ctx.text.strip():
            return []
        lang = "pt" if "pt" in self._langs and (_PT_HINT.search(ctx.text) or "en" not in self._langs) else "en"
        out = []
        for r in self._engine.analyze(text=ctx.text, language=lang, entities=["PERSON"]):
            name = ctx.text[r.start:r.end]
            words = [w for w in re.split(r"\s+", name.strip()) if w]
            if _ORG.search(name) or _ORG_AFTER.match(ctx.text[r.end:r.end + 12]) \
                    or _COPYRIGHT_BEFORE.search(ctx.text[max(0, r.start - 30):r.start]):
                continue  # nome de empresa, não de pessoa
            if len(words) < 2 or not all(w[:1].isupper() for w in words if len(w) > 3):
                continue
            out.append(Finding("pii", 0.72, "Nome de pessoa (NER local)", "nome", r.start, r.end, "[nome]"))
        return out
