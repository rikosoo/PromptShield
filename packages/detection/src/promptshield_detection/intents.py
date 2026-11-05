"""O que a pessoa PEDIU ao assistente (intenção), por regras locais em português e inglês. Só para prompts.

Não muda o score nem a decisão: é um sinal para a análise (quem pede o quê, e quem declara que o conteúdo é confidencial).
Regras simples e transparentes; frases fora do vocabulário ficam sem intenção (lista vazia), nunca "adivinhadas".
Casam em `ctx.folded` (minúsculas, sem acento)."""
from __future__ import annotations

import re

from .models import Context

INTENTS: dict[str, re.Pattern[str]] = {
    "resumir": re.compile(r"\b(?:resum\w+|sumariz\w+|summari[sz]\w*|tl;?dr|em poucas palavras|in a nutshell)\b"),
    "traduzir": re.compile(r"\b(?:tradu\w+|translat\w+)\b"),
    "revisar_corrigir": re.compile(r"\b(?:revis\w+|corrij\w+|corrig\w+|conserte\w*|debug\w*|depur\w+|review\w*|fix(?:es|ed|ing)?|bug|nao funciona|doesn'?t work|not working|erro)\b"),
    "gerar_codigo": re.compile(r"\b(?:escrev\w+|cri[ea]\w*|ger[ae]\w*|implement\w+|write|create|generate|build|make)\b.{0,40}\b(?:codigo|code|funcao|function|script|classe|class|query|sql|teste|tests?|api|endpoint|regex|programa|program)\b"),
    "explicar": re.compile(r"\b(?:explic\w+|como funciona|o que e|o que significa|explain\w*|how does|what is|what does|why does)\b"),
    "reescrever_melhorar": re.compile(r"\b(?:reescrev\w+|melhor(?:e|ar|ia)\w*|aprimor\w+|otimiz\w+|refator\w+|rewrite|improve\w*|optimi[sz]\w*|refactor\w*|polish|reformul\w+)\b"),
    "analisar_extrair": re.compile(r"\b(?:analis\w+|extra[ia]\w*|classific\w+|compar\w+|analy[sz]\w*|extract\w*|classify|categori[sz]e|liste\w*|list all)\b"),
    "validar_verificar": re.compile(r"\b(?:valid\w+|verific\w+|confira\w*|checar|check|verify|confirm\w*)\b"),
    "redigir_texto": re.compile(r"\b(?:escrev\w+|redij\w+|redig\w+|draft|compose|write)\b.{0,30}\b(?:e-?mail|carta|texto|resposta|mensagem|post|relatorio|proposta|ata|letter|message|reply|report|proposal)\b"),
    # declaração do próprio usuário de que o conteúdo é sigiloso: sinal forte de que ele sabe que está compartilhando algo restrito
    "declara_confidencial": re.compile(r"\b(?:confidencia\w+|sigil\w+|segredo|secreto|proprietari[oa]\w*|nao (?:pode|deve) (?:vazar|ser divulgad\w+)|confidential|proprietary|trade secret|internal only|nda|do not share|under embargo)\b"),
}

LABELS = {
    "resumir": "Resumir", "traduzir": "Traduzir", "revisar_corrigir": "Revisar ou corrigir", "gerar_codigo": "Gerar código",
    "explicar": "Explicar", "reescrever_melhorar": "Reescrever ou melhorar", "analisar_extrair": "Analisar ou extrair",
    "validar_verificar": "Validar ou verificar", "redigir_texto": "Redigir texto", "declara_confidencial": "Declara que é confidencial",
}


def detect_intents(ctx: Context) -> list[str]:
    if ctx.kind != "prompt":
        return []
    text = ctx.folded
    return [name for name, rx in INTENTS.items() if rx.search(text)]
