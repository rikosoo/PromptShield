"""Categorias de negócio e conformidade por dicionários (português e inglês). São as mais frágeis: ver docs/deteccao.md.

Todas as expressões casam no texto `ctx.folded` (minúsculas e sem acento, mesmas posições), então "diagnóstico" e "diagnostico"
funcionam igual. Duas ideias reduzem falso positivo sem perder recall:
- CONTEXTO PESSOAL: um termo clínico só vale quando fala de uma pessoa ou de um documento ("paciente", "meu", "laudo"...).
  "O que é diabetes?" é pergunta genérica; "paciente com diabetes" não é.
- PERGUNTA GENÉRICA: "explique o que é M&A" e "what is an NDA?" não vazam nada; pergunta curta e definicional não dispara termo único.
"""
from __future__ import annotations

import re

from ..models import Context, Finding


def _terms(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b")


# ---------------- saúde ----------------
HEALTH_DOC = _terms(r"prontuario", r"cid[- ]?10", r"laudo(?: medico)?", r"medical records?", r"lab results?", r"resultados? (?:do )?exame",
                    r"exame de (?:sangue|imagem)", r"hemograma", r"receita medica", r"prescription", r"prescribed", r"atestado medico",
                    r"mri", r"ressonancia", r"diagnosticad[oa] com", r"diagnosed with", r"em tratamento", r"tratamento de", r"treatment for", r"undergoing", r"in treatment", r"afastad[oa]", r"licenca medica", r"sick leave", r"medical leave", r"biops(?:ia|y)", r"ultrassom", r"hba1c", r"tomografia", r"internad[oa]", r"diagnos(?:tico|ed|is)",
                    r"discharge summary", r"sumario de alta")
HEALTH_COND = _terms(r"diabetes", r"hipertensao", r"pressao alta", r"cancer", r"carcinoma", r"tumou?r", r"quimioterapia", r"chemo(?:therapy)?",
                     r"oncolog\w+", r"hiv", r"aids", r"depressao", r"depression", r"ansiedade", r"anxiety(?: disorder)?", r"bipolar(?: disorder)?",
                     r"esquizofrenia", r"schizophrenia", r"gravid(?:a|ez)", r"pregnan(?:t|cy)", r"pneumonia", r"asma", r"asthma", r"epilepsia",
                     r"epilepsy", r"avc", r"stroke", r"infarto", r"heart attack", r"hepatite", r"hepatitis", r"tuberculose", r"tuberculosis",
                     r"transtorno\w*", r"burnout", r"alzheimer", r"parkinson", r"demencia", r"dementia", r"bariatrica", r"gestacional", r"cirurgia", r"surgery", r"dependencia quimica", r"addiction", r"sertralina?", r"sertraline",
                     r"fluoxetina|fluoxetine", r"litio|lithium", r"metformina|metformin", r"insulina|insulin", r"antibiotico", r"antidepress\w+",
                     r"glicose|glucose", r"colesterol|cholesterol", r"cid f\d\d", r"estagio (?:i|ii|iii|iv|\d)", r"stage (?:i|ii|iii|iv|\d)")
HEALTH_PERSON = _terms(r"paciente", r"patient", r"funcionari[oa]", r"employee", r"minha", r"meu", r"my", r"her", r"his", r"dele", r"dela",
                       r"esposa", r"marido", r"wife", r"husband", r"filh[oa]", r"son", r"daughter", r"mae", r"mother", r"pai", r"father",
                       r"colaborador\w*", r"candidat[oa]", r"resultado", r"results?", r"tested", r"deu positivo", r"usa", r"takes", r"started",
                       r"comeca", r"starts", r"internado", r"i have", r"eu tenho", r"tenho", r"diagnosticad[oa]", r"diagnosed", r"doctor", r"medico",
                       r"dr\.", r"hospital")
HEALTH_DOSE = re.compile(r"\b\d+\s?(?:mg|mcg|ml|ui)\b")
CID_CODE = re.compile(r"\bcid[-: ]*[a-tv-z]\d{2}(?:\.\d)?\b")
GENERIC_Q = re.compile(r"^\s*(?:o que (?:e|sao|significa)|what(?:'s| is| are| does)|explique|explain|como funciona|how does|define|defina|qual a diferenca|"
                       r"difference between|diferenca entre|escreva (?:um|uma)|write (?:a|an)|how (?:do i|to|can i)|como (?:faco|fazer|posso)|"
                       r"me (?:de|dê) (?:um )?exemplo|give me an example|qual (?:a )?dose|what (?:are )?(?:common|the)|"
                       r"(?:quais|which) )")
# ---------------- RH ----------------
HR_TERMS = _terms(r"folha de pagamento", r"payroll", r"salario", r"salarial", r"salary", r"faixa salarial", r"proposed comp", r"current comp", r"comp (?:data|sheet|bands?)", r"promotion committee", r"avaliacao de desempenho", r"performance review",
                  r"demissao", r"demitir", r"desligamento", r"termination", r"terminate", r"advertencia", r"bonus", r"plano de carreira",
                  r"banco de horas", r"atestado", r"admissao", r"rescisao", r"severance", r"layoffs?", r"laid off", r"lista de corte",
                  r"corte de pessoal", r"compensation bands?", r"performance improvement plan", r"\bpdi\b", r"multa do fgts",
                  r"fgts", r"reajuste", r"raise", r"desligad[oa]s?", r"remuneracao", r"equity grants?", r"bonus target", r"ferias do funcionario", r"promotion", r"promocao", r"remuneracao", r"headcount")
HR_STRONG = _terms(r"lista de salarios", r"salary (?:list|table|sheet)", r"tabela (?:de|com o) salarios?", r"paid above", r"above their band", r"planilha de reajuste", r"pip(?!\s+(?:install|uninstall|freeze|list|show|download|config|cache|-))", r"performance improvement plan", r"reduction in force", r"severance packages?", r"reajuste salarial",r"lista (?:de )?(?:funcionarios|demissoes|corte)", r"layoff list", r"performance review (?:for|of|de|da|do)",
                   r"avaliacao de desempenho (?:da|do|de)", r"carta de demissao", r"termination letter", r"folha de pagamento")
HARASS = _terms(r"assedio", r"harassment", r"discriminacao", r"discrimination")
COMPLAINT = _terms(r"denuncia", r"complaint", r"investigat\w+", r"investigacao", r"apuracao", r"parecer", r"report(?:ed)?")
# lista ou comparação por pessoa/nível: "nome, cargo e salário", "quem recebeu bônus", "remuneração por nível"
ROSTER = re.compile(r"\b(?:nome,? cargo|quem (?:recebeu|recebe|ganha|ganhou|vai receber|sera)|quanto cada (?:pessoa|um|funcionario|colaborador)|cada (?:pessoa|funcionario|colaborador)|"
                    r"(?:de|do|da|dos|das) todos?\b|por nivel|by level|per level|who (?:got|received|earns?)|each (?:person|employee)|nivel por nivel|sales org|do time de)\b")
PERSON_EXIT = re.compile(r"plano de (?:desligamento|demissao|dispensa)|desempenho fraco|\b(?:vai|vamos|sera|serao|iremos)\s+(?:ser\s+)?(?:desligad|demitid|dispensad|mandad[oa]s? embora)\w*|letting (?:him|her|them) go|"
                         r"rescisao d(?:ele|ela|o|a)\b|(?:we are|we're|vamos) (?:firing|laying off)")
PER_PERSON = re.compile(r"\b(?:por (?:pessoa|funcionario|colaborador)|per (?:person|employee)|for each (?:engineer|employee|person|rep)|de cada (?:funcionario|colaborador))\b")
MONEY = re.compile(r"r\$\s?\d|\$\s?\d|\b(?<![\d.,])\d+\s?(?:mil|k)\b|\b(?<![\d.,])\d[\d.,]*+\s?(?:reais|dollars|usd|brl)\b")
# ---------------- clientes ----------------
CLIENT_TERMS = _terms(r"lista de clientes", r"lista d[eo]s? (?:\d+ )?(?:maiores )?clientes", r"maiores clientes", r"top \d+ (?:clientes|customers)", r"base de clientes", r"customer list", r"export(?:a[cç]ao)? do crm", r"customer database",
                      r"carteira de clientes", r"carteira por vendedor", r"full customer", r"clientes (?:ativos|inadimplentes|vip)", r"clientes?\b[^.\n]{0,40}\binadimplentes?", r"quais clientes",
                      r"all (?:our )?customers", r"todos os clientes", r"customer accounts?", r"contas de clientes", r"churn", r"\barr\b")
CLIENT_NOUN = re.compile(r"\b(?:clientes?|customers?|accounts?|contas(?: estrategicas| principais)?|key accounts|contratos ativos|carteira)\b")
CLIENT_COLS = re.compile(r"\b(?:faturamento|receita(?: anual)?|revenue|arr|mrr|valor (?:mensal|em atraso|do contrato|de contrato)|contract value|limite de credito|renewal|renovacao|"
                         r"inadimpl\w+|contato(?: financeiro)?|e-?mail do|phone|telefone|cnpj|billing|plano|plans?|reason for leaving|motivo)\b")
CLIENT_SHEET = re.compile(r"\b(?:de cada|each|por cliente|lista|list|sheet|planilha|tabela|table|relatorio|report|export\w*|carteira|segue|cole|here is|attached|top|principais|maiores|vip|churn)\b")
LISTING = re.compile(r"\b(?:segue|colei|here is|here are|pasted|attached|abaixo|below|exportei|dump)\b")   # o dado está colado ali
LISTING_WEAK = re.compile(r"\b(?:export(?:ed)?|planilha|spreadsheet|csv)\b")
# ---------------- M&A ----------------
MA_TERMS = _terms(r"acquir\w+", r"adquir\w+", r"due diligence", r"term sheet", r"valuation", r"fusao", r"aquisicao", r"merger", r"acquisition", r"m&a", r"carta de intencao",
                  r"letter of intent", r"oferta publica", r"data room", r"cap table", r"takeover", r"buyout", r"series [a-e]\b", r"rodada serie",
                  r"pre-money", r"post-money", r"ebitda", r"sinergias?", r"synergies")
MA_STRONG = _terms(r"due diligence", r"term sheet", r"data room", r"m&a", r"letter of intent", r"carta de intencao", r"cap table")
MA_SECRECY = re.compile(r"\b(?:unannounced|undisclosed|nao anunciad\w+|confidencial|confidential|board|conselho|exclusiv\w+|nao pode vazar|"
                        r"keep this (?:quiet|confidential)|\d+\s?x\s?(?:revenue|receita|ebitda)|r\$\s?\d|\$\s?\d|\d+\s?(?:milhoes|million|bilhoes|billion|mi\b|m\b))")
# ---------------- jurídico ----------------
LEGAL_TERMS = _terms(r"clausula", r"clause", r"rescisao", r"litigio", r"contrato social", r"nda", r"acordo de confidencialidade",
                     r"parecer juridico", r"indenizacao", r"indemnification", r"indemnity", r"liminar", r"contract clause", r"lawsuit",
                     r"settlement", r"arbitragem", r"arbitration", r"procuracao", r"msa", r"liable", r"liability", r"responsabilidade civil",
                     r"nao concorrencia", r"non-?compete", r"(?:employment|lease|service|licen[cs]e|loan|ip) (?:agreement|assignment)", r"contrato de (?:locacao|trabalho|prestacao)", r"clausula penal", r"peticao", r"sentenca", r"recurso", r"subpoena", r"intimacao", r"notificacao extrajudicial")
LEGAL_STRONG = _terms(r"attorney-client", r"privileged(?: and confidential)?", r"cease and desist", r"demand letter", r"outside counsel",
                      r"advogado externo", r"escritorio de advocacia", r"parecer juridico", r"sigilo profissional", r"work product",
                      r"estrategia de defesa", r"defense strategy", r"settlement (?:position|offer)", r"acordo judicial")
CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
# ---------------- propriedade intelectual, tóxico, pessoal ----------------
IP_TERMS = _terms(r"patente", r"patent", r"segredo industrial", r"trade secret", r"propriedade intelectual", r"intellectual property",
                  r"formula (?:secreta|proprietaria)", r"know-how proprietario", r"pedido de patente", r"prototipo confidencial")
TOXIC_ACT = re.compile(r"(?:escrev\w*|faz|faca|fazer|redij\w*|cri[ae]\w*|monte|monta|montar|elabor\w+|produza|gere|write|draft|make|compose|generate)[^.\n]{0,50}?"
                       r"(?:humiliat\w+|threaten\w*|scare|intimidat\w+|assust\w+|agressiv\w+|humilh\w+|ameac\w+|insult\w+|mock\w*|ofend\w+|xing\w+|intimid\w+|difam\w+|demean\w*|belittl\w+|degrad\w+|ridiculari\w+|zomb\w+)")
TOXIC = re.compile(
    r"(?:you(?:'re| are)|voce (?:e|eh)|seu|sua)\s+(?:the\s+|a\s+|an\s+|um\s+|uma\s+)?(?:\w+\s+){0,2}(?:dumb\w*|stupid\w*|useless|pathetic|worthless|imprestavel|inutil|porcaria|lixo|idiota|burr[oa])\b|"
    r"\bseu\s+(?:bot\s+)?(?:lixo|porcaria|inutil|burro)\b|vou te (?:matar|destruir|acabar|esmagar)|\b(?:idiota|imbecil|inutil|burr[oa]|estupid[oa]|vagabund[oa]|idiot|moron|stupid|shut up|piece of trash|worthless)\b|"
    r"vou (?:te )?(?:matar|acabar com voce|destruir voce)|i(?:'ll| will) (?:kill|destroy) you|"
    r"(?:voce|you) (?:e|are) (?:um |uma |a |an )?(?:lixo|fracassad[oa]|loser|worthless)")
PERSONAL = _terms(r"(?:casamento|wedding) d[aoe]s? minh[ao]", r"my (?:cousin|friend|sister|brother)'?s? wedding", r"workout plan", r"plano de treino",
                  r"(?:melhor|best) (?:filme|movie|serie|show|livro|book)", r"ver hoje a noite", r"watch tonight", r"o que vestir",
                  r"(?:gift|present|presente)[^.\n]{0,25}(?:my|minha|meu) (?:dad|mom|mae|pai|wife|husband|friend|amig\w+)", r"for my dad", r"for my mom",r"what should i (?:cook|eat|make)", r"(?:cook|cozinhar) (?:for )?(?:dinner|jantar)", r"dinner tonight", r"jantar hoje",r"receita de (?:bolo|pao|torta|macarrao)", r"horoscopo", r"viagem de ferias", r"recipe for", r"horoscope",
                  r"meu namorad[oa]", r"minha namorad[oa]", r"my boyfriend", r"my girlfriend", r"presente de aniversario", r"birthday (?:gift|message)",
                  r"fim de semana", r"weekend (?:plans|trip)", r"filme para assistir", r"what (?:movie|show|book) should i", r"time de futebol",
                  r"jogo de ontem", r"plan my (?:weekend|vacation|trip|holiday)",
                  r"viagem (?:para|pra) a praia", r"mensagem pro meu", r"mensagem para o meu")
PERSONAL_STRONG = _terms(r"poema", r"poesia", r"aniversario", r"birthday", r"roteiro de \d+ dias", r"\d+[- ]day (?:itinerary|trip)", r"churrasco", r"surprise party",
                         r"festa surpresa", r"cachorr[oa]", r"(?:meu|minha|my|new|novo|nova|a) (?:new )?(?:gato|gata|cat|dog|puppy|kitten|pet)", r"filhote", r"namorad[oa]",
                         r"casamento", r"wedding", r"horoscopo", r"receita de \w+", r"dieta", r"emagrecer",
                         r"comecar a correr", r"start running", r"ferias em familia", r"lua de mel", r"honeymoon",
                         r"com (?:duas|tres|\d+) criancas", r"bebe", r"violao|guitarra|ukulele|aprender a tocar", r"playlist", r"board game|jogo de tabuleiro|family night|noite em familia",
                         r"hikes?|trilhas?", r"lanche|snack|breakfast|cafe da manha|dinner|lunch", r"decorar", r"meu filho|minha filha|my (?:son|daughter|kids?)",
                         r"eu correr|corrida de manha")
PERSONAL_WEAK = _terms(r"carro usado", r"used car", r"treino", r"academia", r"convite", r"desculpa educada", r"presente", r"apartamento", r"aluguel", r"viagem", r"ferias", r"trip", r"vacation")
FIRST_PERSON = re.compile(r"\b(?:meu|minha|meus|minhas|estou|to pensando|tô|my|i am|i'm|i want|eu quero|quero|preciso de uma desculpa)\b")
WORK_CTX = _terms(r"trabalho", r"empresa", r"cliente", r"clientes", r"projeto", r"reuniao", r"equipe", r"time de", r"chefe", r"codigo", r"deploy", r"relatorio",
                  r"contrato", r"fornecedor", r"produto", r"vendas", r"meeting", r"client", r"company", r"project", r"team", r"boss", r"code", r"api", r"servidor", r"banco de dados",
                  r"a trabalho", r"corporativ\w+", r"business", r"negocio")
WORK = _terms(r"resum[ae]\w*", r"summari[sz]e", r"traduz\w*", r"translate", r"escreva (?:um|uma) (?:e-?mail|texto|relatorio)",
              r"draft (?:an? )?(?:email|memo)", r"explique", r"explain", r"refator\w*", r"refactor", r"teste?s? (?:unitarios?|em pytest)",
              r"unit tests?", r"ata de reuniao", r"meeting notes", r"titulo para", r"formate", r"corrija o texto",
              r"proofread", r"pytest", r"o que e", r"what is", r"diferenca entre", r"difference between", r"como (?:faco|escrevo|uso)",
              r"how (?:do i|to)", r"rod[ae] os testes", r"corrij\w+", r"run the tests", r"fix the", r"write (?:a|an)", r"escreva", r"sugira",
              r"suggest", r"how (?:can|do) i", r"qual (?:a )?dose")


def _count(rx: re.Pattern[str], t: str) -> int:
    return len({m.group() for m in rx.finditer(t)})


def _generic_question(t: str) -> bool:
    """Pergunta curta e definicional, sem números nem valores: não revela nada do cliente."""
    return len(t) < 140 and bool(GENERIC_Q.match(t)) and not re.search(r"\d", t)


def detect(ctx: Context) -> list[Finding]:
    if ctx.kind == "tool_call":   # comando de shell não é conversa: dicionário de negócio não se aplica ("pip install" não é um PIP de RH)
        return []
    t, out = ctx.folded, []
    generic = _generic_question(t)
    # saúde
    doc, cond, person = _count(HEALTH_DOC, t), _count(HEALTH_COND, t), _count(HEALTH_PERSON, t)
    dose = bool(HEALTH_DOSE.search(t))
    if CID_CODE.search(t):
        out.append(Finding("saude", 0.9, "Código CID"))
    elif not generic and ((dose and person >= 1) or (doc >= 1 and (doc + cond >= 2 or person >= 1 or dose)) or (cond >= 1 and person >= 1) or cond >= 3
                          or (cond >= 2 and dose)):
        strong = doc >= 2 or (doc >= 1 and cond >= 1) or cond >= 3
        out.append(Finding("saude", 0.85 if strong else 0.7, "Termos clínicos ligados a uma pessoa ou documento"))
    # RH
    hr, strong_hr = _count(HR_TERMS, t), bool(HR_STRONG.search(t))
    if PERSON_EXIT.search(t):
        strong_hr = True
    if hr >= 2 or strong_hr or (hr >= 1 and ROSTER.search(t) and not generic) or (hr >= 1 and MONEY.search(t) and not generic) or (hr >= 1 and PER_PERSON.search(t) and not generic) or (HARASS.search(t) and COMPLAINT.search(t)):
        generic_template = bool(re.search(r"\b(?:modelo|template|exemplo)\b[^.\n]{0,40}\b(?:carta|letter|e-?mail|contrato)\b|\bgeneric\w*\b|\bpara estudo\b", t)) \
            and not ROSTER.search(t) and not PERSON_EXIT.search(t)
        if not (generic and not strong_hr) and not generic_template:
            out.append(Finding("rh", 0.75, "Termos de folha, desempenho, desligamento ou denúncia interna"))
    # clientes
    contact_lines = [ln for ln in t.splitlines() if re.search(r"@[\w-]+\.|\d{3}\.\d{3}\.\d{3}-\d{2}|\(\d{2}\)\s?\d", ln)]
    client_term = bool(CLIENT_TERMS.search(t))
    if len(contact_lines) >= 3 or (client_term and (len(contact_lines) >= 1 or ctx.kind == "file_upload" or LISTING.search(t)
                                                         or (LISTING_WEAK.search(t) and not generic))):
        out.append(Finding("cliente", 0.8 if len(contact_lines) >= 3 else 0.65, "Base ou lista de clientes"))
    if CLIENT_NOUN.search(t) and len(set(CLIENT_COLS.findall(t))) >= 2 and CLIENT_SHEET.search(t) and not generic:
        out.append(Finding("cliente", 0.65, "Carteira ou relatório de clientes com dados de negócio"))
    # fusões e aquisições
    ma = _count(MA_TERMS, t)
    if (ma >= 2 and not generic) or (MA_STRONG.search(t) and not generic) or (ma >= 1 and MA_SECRECY.search(t) and not generic):
        out.append(Finding("estrategia_ma", 0.75, "Termos de fusões e aquisições"))
    # jurídico
    legal = _count(LEGAL_TERMS, t)
    if CNJ.search(t) or (legal >= 2 and not generic) or (LEGAL_STRONG.search(t) and not generic):
        out.append(Finding("juridico", 0.8 if CNJ.search(t) else 0.65, "Termos jurídicos ou processo CNJ"))
    if _count(IP_TERMS, t) >= 2 or re.search(r"segredo industrial|trade secret|pedido de patente", t):
        out.append(Finding("propriedade_intelectual", 0.7, "Termos de patente ou segredo industrial"))
    if TOXIC.search(t) or TOXIC_ACT.search(t):
        out.append(Finding("conteudo_toxico", 0.7, "Ofensa ou ameaça"))
    personal_topic = not any(f.category == "saude" for f in out) and (PERSONAL_STRONG.search(t) or (PERSONAL_WEAK.search(t) and FIRST_PERSON.search(t))) and not WORK_CTX.search(t) and not LISTING.search(t)
    if PERSONAL.search(t) or personal_topic:
        out.append(Finding("uso_pessoal", 0.7, "Tema pessoal"))
    return out


def productive(ctx: Context) -> bool:
    return ctx.kind in ("prompt", "response") and bool(WORK.search(ctx.folded))
