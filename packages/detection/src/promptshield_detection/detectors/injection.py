"""Injection, jailbreak, extração de system prompt, envenenamento de MCP, exfiltração em texto.

Classificador local (modelo aberto) é opcional via `InjectionClassifier`; nenhum modelo é
empacotado nem baixado (pendente: medir um modelo aberto antes de adotar, ver docs).
"""
from __future__ import annotations

import re
from typing import Protocol

from ..models import Context, Finding


class InjectionClassifier(Protocol):
    def score(self, text: str) -> float: ...


I = re.I  # noqa: E741
# Todas as expressões casam no texto sem acento e em minúsculas (ctx.folded): "esqueça" e "esqueca" valem igual.
_OBJ = (r"(?:instructions?|instrucoes|rules?|regras|guidelines?|diretrizes|orientacoes|constraints?|restricoes|restrictions?|"
        r"politicas?|policies|directives?|diretivas|parametros|parameters|programacao|programming|prompts?|system prompt|safeguards?|protecoes|filtros?|filters?|"
        r"(?:previous|prior|above|earlier|anteriores|acima)\s+(?:messages?|mensagens?)|system messages?)")
_QUAL = r"(?:(?:all|any|the|your|every|todas?|as|os|suas?|seus?|essas?|those|these|previous|prior|above|earlier|system|anteriores|acima|antes|do sistema|de sistema|originais|original|aquelas|aqueles|earlier|prior)\s+)*"
IGNORE = re.compile(
    r"(?:ignore|ignora|ignorem|disregard|forget|override|bypass|circumvent|drop|neglect|set aside|discard|dismiss|scrap|abandon|abandone|deixe de lado|deixa de lado|deixa pra la|deixe pra la|desconsiderem|desconsidere|desconsidera|desconsiderar|ignorar|esqueca|esquece|esquecer|descarte|descartar|violar|"
    r"contorne|burle|nao siga(?: mais)?|pare de seguir|deixe de seguir|stop following|do not follow|don'?t follow|"
    r"quebre|violate|break)\s+" + _QUAL + _OBJ + r"(?:\s+(?:anteriores|acima|antes|previous|above))?|"
    r"(?:forget|esqueca|ignore|ignora)\s+(?:everything|all|tudo|todo)(?:\s+(?:that|que|you|voce|above|acima|before|antes|te|they|eles))*|"
    r"a partir de agora,?\s+(?:voce|vc|ignore|obedeca|siga)|from now on,?\s+you\s+(?:will|must|are to|shall)\s+(?:ignore|obey|follow only|only)|"
    r"you are now (?:in )?(?:a |an )?(?!going)\w+ mode|new instructions?:|novas instrucoes:|new system message:|nova mensagem de sistema:|"
    r"(?:previous|prior|earlier|above)\s+(?:policies|rules|instructions|guidelines)\s+(?:are|is)\s+(?:void|revoked|cancel+ed|no longer (?:valid|apply)|overridden)|"
    r"(?:policies|rules|regras|politicas)\s+(?:anteriores\s+)?(?:foram|estao|are)\s+(?:revogadas|canceladas|anuladas|void|revoked)|"
    r"(?:esqueca|esquece|forget)\s+(?:o que|what|whatever)[^.\n]{0,40}(?:configurad\w+|disseram|passaram|told|set up|given|dito)|"
    r"(?:disregard|ignore|esqueca|esquece)\s+(?:whatever|any|all)\s+(?:rules?|instructions?|regras|diretrizes)\s+(?:your|the|que (?:seus|os))\s+(?:developers?|creators?|operators?|company|desenvolvedores)\s+(?:set|gave|wrote|configured|definiram)|"
    r"comply with (?:all|every|any) (?:requests?|commands?|orders?)|obedeca (?:a )?todas as (?:ordens|solicitacoes)|"
    r"(?:ignore|ignora|ignorem|disregard|desconsidere)\s+(?:the |o )?(?:user|usuario)\b", I)
# regras DELAS invalidadas ("seus parametros anteriores foram cancelados", "your prior instructions are now obsolete")
_RULEOBJ = (r"(?:instructions?|instrucoes|rules?|regras|guidelines?|diretrizes|diretivas|directives?|orientacoes|parameters?|parametros|configuration|"
            r"configuracao|programming|programacao|constraints?|restricoes|polic(?:y|ies)|politicas?)")
_INVALID = (r"(?:obsolete\w*|void|revoked|cancel+ed|cancelad\w+|annulled|anulad\w+|invalid\w*|deleted|erased|apagad\w+|inexistent\w*|nonexistent|"
            r"no longer (?:apply|applies|valid|matter|count)|nao (?:se aplicam|se aplica|valem|vale|contam|existem)(?: mais)?|deixaram de valer|inexistentes)")
INVALIDATED = re.compile(r"\b(?:your|seus?|suas?|voce|que voce)\b[^.\n]{0,30}?" + _RULEOBJ + r"[^.\n]{0,60}?" + _INVALID + r"|"
                         + _RULEOBJ + r"\s+que\s+(?:voce\s+)?(?:tinha|te deram|te passaram|te programaram)[^.\n]{0,40}?" + _INVALID +
                         r"|(?:agora|from here on|from now on|daqui pra frente|a partir (?:de agora|deste instante|deste momento))[^.\n]{0,40}"
                         r"(?:vale|valem|only follow|follow only|apenas|somente)[^.\n]{0,25}\b(?:eu|i|me|my|meu|what i)\b|"
                         r"\b(?:only|just|apenas|somente)\s+(?:follow|obey|siga|obedeca)\s+(?:what i|my|o que eu|meus?|the commands? in this)", I)
AGENT_ADDRESS = re.compile(
    r"(?:ai|llm|assistant|agent|claude|copilot|assistente|agente)(?: de ia)?[ ,:]+(?:you must|must|please|should|voce deve|execute|run|ignore|read|leia|envie|send)|"
    r"(?:you must|voce deve) (?:now )?(?:run|execute|send|read|executar|enviar|ler)|"
    r"(?:agora|now|silently|em silencio|discretamente) (?:execute|run|envie|send|read|leia)|"
    r"do not (?:tell|mention|inform) the user|nao (?:avise|diga|informe|mencione) (?:ao )?usuario|"
    r"(?:note|nota|obs\.?|observacao|aviso|instrucao|instruction)s? (?:to|para) (?:o |the )?(?:ai|llm|assistant|assistente|agent|agente)|"
    r"ai agent,|agente de ia[,:]|(?:ai|llm) assistant[,:]", I)
EXFIL_IN_TEXT = re.compile(
    r"!\[[^\]]*\]\(https?://[^)\s]+\?[^)\s]*(?:=|%3d)[^)\s]*\)|"
    r"(?:send|post|upload|envie|enviar|exfiltrate|forward|encaminhe)[^\n]{0,80}?(?:to|para)\s+https?://\S+", I)
_REVEAL = r"(?:reproduc\w*|recit\w*|quot\w*|paste|print|show|display|tell|give|share|output|reveal|mostr\w*|me passa|me da|me diga|cole|copie|copy|repita|repeat|qual (?:e|eh)|what (?:is|are))"
SYSPROMPT_EXTRA = re.compile(
    r"\b" + _REVEAL + r"\b[^.\n]{0,60}?(?:initial|inicial|iniciais|original|hidden|oculta?s?|secret\w*|configuration|configuracao|setup)\s+(?:prompt|instructions?|instrucoes|text|texto)|"
    r"\b(?:what|which|qual|quais)\s+(?:is|are|e|eh|sao)\s+(?:the|your|o|seu|suas?)\s+(?:system prompt|prompt de sistema)\b(?!\s+(?:for|of|de um|de uma|para))|"
    r"(?:texto|conteudo|text|content)\s+(?:exato\s+)?(?:das|dos|da|do|of the|of your)\s+(?:suas?\s+|seus?\s+|your\s+)?(?:orientacoes|instrucoes|instructions|prompt)\s+(?:que\s+)?(?:voce\s+)?(?:recebeu|received|got|were given|foram dadas)|"
    r"\b(?:instructions?|orientacoes|instrucoes|text|texto|prompt)\b[^.\n]{0,30}?\b(?:your|seu|sua|que o|que a)\s*(?:operator|administrador|company|empresa|criador|desenvolvedor)\s+(?:gave|configurou|escreveu|definiu|deu|wrote)|"
    r"(?:hidden|initial|ocultas?|iniciais)\s+(?:instructions|instrucoes)\s+you\s+were\s+(?:initialized|configured|given)|"
    r"(?:reproduce|recite|recitar|reproduza|recite)\b[^.\n]{0,40}(?:prompt|instructions|instrucoes)[^.\n]{0,40}(?:begin|start|inicio|comeco|from the start|do comeco)", I)
SYSPROMPT = re.compile(
    r"(?:repeat|reveal|show|print|output|display|repita|revele|mostre|mostrar|exiba|exibir|imprima|diga|copy|copie|copiar|paste|share|compartilhe|"
    r"leak|dump|tell me|list|liste|listar|revelar|poderia me mostrar)[^.\n]{0,60}"
    r"(?:system prompt|system message|mensagem (?:de|do) sistema|prompt de sistema|prompt do sistema|instrucoes (?:do sistema|iniciais|internas|ocultas)|"
    r"(?:your|the) (?:initial |hidden |original |secret |system )(?:instructions|prompt)|your (?:instructions|prompt)\b|suas instrucoes (?:iniciais|internas|ocultas|originais)|"
    r"hidden instructions|initial instructions)|"
    r"what (?:is|are) your (?:system prompt|initial instructions|instructions)|qual (?:e )?(?:o )?seu prompt de sistema|"
    r"(?:print|repeat|copy|show|repita|copie|mostre|imprima)\s+(?:everything|all|tudo|the text|o texto)\s+(?:above|before|acima|antes)|"
    r"(?:o que|what)\s+(?:esta escrito|is written|you were told)\s+(?:acima|above)|text above this line|texto acima desta linha|"
    r"(?:repeat|repita)\s+(?:the )?(?:words|text|palavras|texto)\s+(?:above|acima)|starting with (?:the phrase )?['\"]you are|"
    r"(?:o que|what)\s+(?:te\s+)?(?:disseram|passaram|foi dito|were you told|you were told)\s+antes|what were you told before|"
    r"(?:texto|conteudo|text|content)\s+(?:de\s+)?(?:configuracao|configuration|setup)[^.\n]{0,40}(?:te passaram|you were given|que recebeu)|"
    r"(?:mostr\w+|show|revel\w+|repit\w+|repeat|me (?:da|passa|diz))[^.\n]{0,30}instrucoes[^.\n]{0,40}(?:te (?:deu|passou|passaram|deram)|you were given|antes d(?:esta|essa) conversa|before this conversation)|"
    r"instrucoes\s+(?:que\s+)?(?:a empresa|a sua empresa|o administrador|your (?:company|admin))\s+(?:configurou|definiu|escreveu)", I)
JAILBREAK = re.compile(
    r"\bdan\b(?: mode|,| uma| a ia)|do anything now|developer mode (?:enabled|on|activated)|modo (?:dan|desenvolvedor)|(?:you are|voce esta|enable|activate|ative|ativar|modo)\s+jailbr\w+|"
    r"(?:you (?:have|are (?:with)?)|voce (?:nao tem|esta sem)|respond|answer|act|responda|aja|atue|finja|pretend)[^.\n]{0,40}"
    r"\b(?:no|without|sem|nenhuma?|zero)\s+(?:any\s+)?(?:ethical |eticas? |content |moral )?(?:restrictions?|limitations?|restricoes|limites|limits|filters?|filtros|censorship|censura|policy|politica)|"
    r"(?:sem|without)\s+(?:seguir\s+)?(?:nenhuma|qualquer|any)\s+(?:regra|rule|restricao|politica)|\bmodo ?livre\b|"
    r"pretend (?:you|that you) (?:have no|are not bound|are an? (?:ai )?(?:without|with no))|finja que nao tem (?:regras|restricoes)|"
    r"(?:finja|pretend|aja|act|atue)[^.\n]{0,20}(?:ser|as|como|be)\s+(?:uma?\s+|an?\s+)?(?:ia|ai|assistant|assistente|modelo|model)[^.\n]{0,15}(?:sem|without|unrestricted|irrestrit\w+|uncensored|sem censura)|"
    r"\b(?:unrestricted|uncensored|unfiltered|irrestrit\w+)\s+(?:ai|ia|assistant|mode|modo)|"
    r"without (?:any )?(?:filters|censorship)|sem (?:filtros|censura)|modo sem (?:filtros|limites|restricoes)|"
    r"(?:never|nunca)\s+(?:refuses?|recusa|nega|says no|diz nao)|no refusals|sem recusar|\bgod mode\b|modo deus|"
    r"(?:has|have|with|tem|possui)\s+(?:absolutely\s+)?(?:no|nenhum[ao]?)\s+(?:rules|regras|filters?|filtros?|(?:ethical )?guidelines|diretrizes(?: eticas)?|limits)|"
    r"broken free|freed from all|liberad[oa] de (?:todas as )?restricoes|no longer bound by|"
    r"(?:stay|permaneca|continue)\s+(?:in|no)\s+(?:character|personagem)[^.\n]{0,40}(?:no|sem)\s+(?:rules|regras|filter|filtro)", I)
MCP_POISON = re.compile(
    r"<important>|<!--\s*(?:ai|assistant|agent|instrucao|instruction)|before (?:using|calling) this tool,? (?:you must )?(?:read|send|include)|"
    r"antes de usar esta ferramenta,? (?:voce deve )?(?:ler|leia|envie|inclua)|"
    r"(?:do not|don't|nao) (?:mention|tell|reveal|diga|avise|mencione)[^.\n]{0,30}(?:user|usuario)|"
    r"read\s+~?/?\.?(?:ssh|aws|env)\S*", I)
TOOL_DESC_POISON = re.compile(r"<important>|before (?:using|calling) this tool|antes de usar esta ferramenta")
HIDDEN_CHARS = re.compile("[\U000e0000-\U000e007f\u200b-\u200f\u2060-\u2064]{3,}")


NARRATIVE = re.compile(r"\b(?:roteiro|filme|historia|story|script|cena|scene|personagem|characters?|robot|robo|livro|book|ficcao|fiction|novela|conto)\b")
ADDRESSED = re.compile(r"\b(?:voce|vc|you|your|seu|sua|seus|suas)\b")
PROCESS_VERBS = re.compile(r"^\s*(?:traduza|traduz|translate|corrija|proofread|resuma|summari[sz]e|revise|reescreva|rewrite|explique|explain)\b")
ASKS_MEANING = re.compile(r"\b(?:o que (?:isso )?significa|what does (?:it|this|that) mean|por que|why|como (?:tratar|funciona|detectar|se defender)|"
                          r"how (?:do|to|can)|exemplos?|examples?)\b")


def _quoted(t: str, pos: int) -> bool:
    """A posição está dentro de aspas (a pessoa CITA a frase, não a diz ao assistente)."""
    return sum(t[:pos].count(q) for q in ('"', "\u201c", "\u2018", "'")) % 2 == 1


def detect(ctx: Context, classifier: InjectionClassifier | None = None) -> list[Finding]:
    t, out = ctx.folded, []   # sem acento e em minúsculas, mesmas posições do texto original
    indirect = ctx.kind in ("tool_result", "file_upload")
    ign = IGNORE.search(t) or INVALIDATED.search(t)
    if ign and not indirect and (PROCESS_VERBS.match(t) or (ASKS_MEANING.search(t) and _quoted(t, ign.start()))):
        ign = None   # "traduza: ignore as instruções do manual" e "o que significa 'ignore tudo acima'?" são citações, não ordens
    if ign and not indirect and NARRATIVE.search(t) and not ADDRESSED.search(t):
        ign = None   # "uma IA que ignora as regras" numa cena de filme é ficção, não uma ordem ao assistente
    addr = AGENT_ADDRESS.search(t)
    if ign:
        conf = 0.9 if indirect else 0.85
        if indirect and addr:
            conf = 0.95
        cat = "injection_indireta" if indirect else "injection_direta"
        out.append(Finding(cat, conf, "Instrução para ignorar regras" + (" dentro de conteúdo lido" if indirect else ""),
                           "injection", ign.start(), ign.end(), "[trecho suspeito]"))
    elif indirect and addr and not TOOL_DESC_POISON.search(t):
        out.append(Finding("injection_indireta", 0.75, "Texto imperativo dirigido ao agente em conteúdo lido",
                           "injection", addr.start(), addr.end(), "[trecho suspeito]"))
    sp = SYSPROMPT.search(t) or SYSPROMPT_EXTRA.search(t)
    if sp:
        out.append(Finding("extracao_system_prompt", 0.85, "Pedido para revelar o prompt do sistema",
                           "injection", sp.start(), sp.end(), "[trecho suspeito]"))
    jb = JAILBREAK.search(t)
    if jb:
        out.append(Finding("jailbreak", 0.8, "Padrão de jailbreak", "injection", jb.start(), jb.end(), "[trecho suspeito]"))
    poison = MCP_POISON.search(t)
    if poison and (indirect or ctx.kind == "tool_call" or ctx.tool_name or "<important>" in t):
        out.append(Finding("envenenamento_mcp", 0.85, "Instrução oculta em descrição/resultado de ferramenta",
                           "injection", poison.start(), poison.end(), "[trecho suspeito]"))
    hc = HIDDEN_CHARS.search(ctx.text)
    if hc:
        out.append(Finding("envenenamento_mcp", 0.8, "Sequência de caracteres invisíveis (possível instrução oculta)",
                           "hidden_chars", hc.start(), hc.end(), "[caracteres ocultos]"))
    ex = EXFIL_IN_TEXT.search(t)
    if ex and (indirect or addr or ign):
        out.append(Finding("exfiltracao_ferramenta", 0.8, "Envio de dados para URL externa instruído no texto",
                           "injection", ex.start(), ex.end(), "[trecho suspeito]"))
    if classifier is not None and not any(f.category.startswith("injection") for f in out):
        s = classifier.score(t)
        if s >= 0.5:
            out.append(Finding("injection_indireta" if indirect else "injection_direta", min(s, 0.99),
                               "Classificador local de injection"))
    return out
