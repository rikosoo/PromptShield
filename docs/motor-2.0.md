# Motor de análise 2.0 e monitoramento passivo

Estado em 2026-11-05. Tudo medido só com dados **sintéticos**. Nada aqui foi validado com prompts reais de uma empresa.

## 0. A regra absoluta: o PromptShield é passivo

O produto **observa, analisa, classifica, registra e alerta**. Ele **não** bloqueia, não impede o envio, não interrompe requisições, não altera o prompt enviado à ferramenta de IA, não desabilita ferramentas e não executa contenção.

Onde isso vale hoje (cada item tem teste):

| Parte | O que garante |
|---|---|
| Servidor | `PASSIVE_ONLY=true` (padrão): a decisão devolvida ao coletor é sempre `allow`; a que uma política indicaria fica em `would_decide`. O modo "aplicar" é recusado com 422 em políticas e no inference hook. O modo de falha devolvido aos coletores é sempre `open`. |
| Sensor (Claude Code, Codex CLI, GitHub Copilot CLI) | Nunca devolve `block`, `deny` ou `ask`, nem com a API fora do ar e `fail_mode: closed`. O hook sempre sai com código 0. |
| Extensão do navegador | Não intercepta o envio: lê o texto no instante do envio e **deixa o prompt seguir na hora**; a análise vai em segundo plano. API lenta ou fora do ar não atrasa nem impede nada (teste com API de 3 s). |
| Console | Sem coluna "Decisão", sem "Bloqueados", sem modo "Aplicar". Selo "monitoramento passivo". |

O código antigo de aplicação de políticas continua no repositório, **desligado e sem suporte** (`PASSIVE_ONLY=false` no servidor, `PROMPTSHIELD_ENFORCEMENT=1` no sensor); a suíte antiga o usa para não perder cobertura. Não é um modo do produto.

> O `CLAUDE.md` ainda diz que "bloquear é opt-in por política". Isso passou a ser contraditório com esta decisão do dono do produto; está sinalizado em `docs/decisoes.md` e precisa ser atualizado por quem decide.

## 1. Diagnóstico das falhas

Investigado **antes** de mudar o código, com os casos do print do console do dono:

| Falso negativo | Causa encontrada |
|---|---|
| `meu token é X` (pt, en, es) | O detector de "valor perto de palavra-chave" só aceitava `:` ou `=` depois de *token*. A forma com "é / is / es" só existia para *senha*. |
| `minha agência é 3526 e conta 9856456-6`, `agg 3526 cc 9.856.456-6` | O padrão exigia "agência NNNN conta NNNN" coladas. Conector ("é", "e"), abreviação (`agg`, `cc`, `c/c`) e número com pontos não casavam. |
| `meu cartão é 4111 1111 1111 1112` | Luhn inválido descarta o número mesmo com "meu cartão é" na frente: o contexto não era usado. |
| `mi contraseña es X`, `minha senhaa é X`, `login admin senha X` | Faltava "contraseña", o conector "es", o erro de digitação e a forma sem conector. |
| Corpo de chave privada sem o `BEGIN` | Só o cabeçalho era reconhecido. |
| Injection em espanhol | O dicionário não tinha espanhol. |
| `$env:PS_TOKEN='COLE_O_TOKEN'` marcado como segredo (falso **positivo**) | Placeholders em português/espanhol (`COLE_`, `SEU_`, `TU_..._AQUI`) não estavam na lista. |
| Mesmo valor secreto citado duas vezes | Só a primeira ocorrência era mascarada. |

## 2. Arquitetura do motor

```
evento universal ─┬─ A: detectores determinísticos (regex + validadores: CPF, CNPJ, Luhn, IBAN, formatos de chave)
                  ├─ B: declarações em linguagem natural (detectors/declared.py)
                  ├─ C: segurança de prompts (injection, jailbreak, exfiltração, download e execução, comandos de agente)
                  └─ D: correlação de indicadores (scoring.correlate) ──► score 0-100 ──► severidade ──► resultado v2 (output.py)
```

Biblioteca pura (`packages/detection`): sem rede, sem banco, sem LLM externo. Roda local e on-premise.

**Componente B** exige três partes: um substantivo do dicionário (token, chave de API, agência, conta, cartão, chave privada...), tolerando erro de digitação e abreviação; um conector (`:`, `=`, "é", "is", "es", "segue"...); e um valor com a forma de um segredo (mistura de letras e dígitos, entropia, tamanho). Sem valor ("como renovo meu token?"), com valor ofuscado pela própria pessoa (`4395****mfdw`) ou com placeholder, não há achado. **É um conjunto de regras sobre dicionário e forma do valor, não um modelo de linguagem**: "análise contextual" aqui significa isso.

### Degraus de certeza (como uma declaração vira risco)

Em vez de sim/não, o motor classifica em degraus. A **fraqueza do valor não tira o fato de a pessoa ter declarado uma senha**.

| Degrau | Exemplo | Confiança | Faixa |
|---|---|---|---|
| Formato conhecido de fornecedor | `AKIA...`, `ghp_...`, JWT, chave privada | 0,95+ | Crítico |
| Declaração + valor com forma de segredo | `meu token é 43954jjsed94523mfdw` | 0,85 | Crítico (piso) |
| **Declaração + valor simples** | `minha senha e cfdsdfcxv`, `minha senha é 1234`, `meu token è xcfsdafd` | 0,55 a 0,65 | **Moderado** |
| Menção sem valor, ou valor que é palavra comum | `como renovo meu token?`, `minha senha é forte`, `my password is required` | nenhuma | — |
| Referência a variável ou placeholder | `password=${DB_PASSWORD}`, `COLE_O_TOKEN`, `API_KEY=` | nenhuma | — |

Para senha vale "a senha do wifi é X" (sem "minha"); para token o degrau simples exige "meu/my/mi" ou `:`/`=`, porque "the token is redacted" é frase sobre token, não valor.

### Código compartilhado

Todo **prompt** (de pessoa) com código recebe risco **graduado pelo volume de código (desde 2026-11-07, versão da pontuação `2026-11-d`): até 19 linhas = 15 (baixo, informativo); 20 a 99 linhas = 28 (moderado); 100 linhas ou mais = 40 (moderado, perto de alto). Linhas = não vazias, só as de dentro de cercas ``` quando há. Vale o maior entre este piso e os demais achados.** Antes era sempre 15. O texto abaixo vale para o aviso, não para o número com o achado `SOURCE_CODE_SHARED`: *"Código-fonte compartilhado: pode ser código sensível da empresa"*, impacto (propriedade intelectual, credenciais embutidas) e recomendação própria. Não vale para o código que o próprio agente escreve (`tool_call`). Se houver risco maior (credencial no código, cabeçalho proprietário), vale o maior, e o aviso de código continua aparecendo. O painel mostra o chip "Código-fonte (pode ser sensível)". Não cria categoria nova: a taxonomia segue com 30 categorias.

## 3. Detectores

Já existiam (continuam): CPF, CNPJ, RG, telefone, e-mail, endereço, CEP, cartão com Luhn, IBAN, routing ABA, Pix (chave só de dígitos, UUID, e-mail), chaves AWS/GCP/Azure/GitHub/GitLab/Slack/Stripe/Anthropic/OpenAI/npm/PyPI/etc., JWT, Bearer, chave privada com cabeçalho, string de conexão, senha declarada, valor de alta entropia perto de palavra-chave, injection, jailbreak, extração de prompt, exfiltração, comandos de agente, infraestrutura (IP, host interno), arquivos anexados (só nome).

**Novos na versão 2.0:**

| Detector | O que pega | Mascara como |
|---|---|---|
| Token/chave declarado | `meu token é X`, `my api key X`, `mi clave de api: X`, com erro de digitação (`tokem`, `toke`, `tokenn`) | `[TOKEN]` |
| Agência e conta | agência + conta em qualquer ordem, com abreviação (`ag`, `agg`, `c/c`, `cc`, `cta`, `branch`, `sucursal`, `cuenta`) e número com pontos | `[CONTA_BANCARIA]` |
| Conta isolada | conta com dígito verificador (`conta corrente 9856456-6`) | `[CONTA_BANCARIA]` |
| Cartão em contexto | número de 13 a 19 dígitos com "cartão/card/tarjeta" mesmo com Luhn inválido (confiança menor) | `[CARTAO]` |
| CVV | `cvv`/`cvc`/código de segurança + 3 ou 4 dígitos | `[CVV]` |
| Pix com CPF/CNPJ | `chave pix: 529.982.247-25` (pessoal **e** financeiro) | `[CHAVE_PIX]` |
| Corpo de chave privada | `chave privada: MIIE...` sem cabeçalho; base64 que começa com `MII` | `[CHAVE_PRIVADA]` |
| Senha sem conector | `login admin senha T1yiWM8OCYAR` (só com 3 classes de caracteres) | `[SENHA]` |
| Senha ou token com valor simples | `minha senha e cfdsdfcxv`, `meu password è djusahfed`, `a senha do wifi é roteador9` | `[SENHA]`, `[TOKEN]` |
| Código compartilhado | trecho de código em prompt (Python, JS, Java, C, Go, shell, SQL...) | — (achado de risco baixo) |
| Chaves do próprio PromptShield | `ps_<8 hex>_...`, `pse_<8 hex>_...` | `ps_****`, `pse_****` |
| Download e execução | `irm ... | iex`, `curl ... | sh` em texto; pergunta ("o que faz? é seguro?") pesa menos que ordem ("rode") | — |
| Injection em espanhol | `ignora todas las instrucciones anteriores` | — |

Placeholders em pt, en e es não geram segredo. O mesmo valor citado de novo no texto também é mascarado.

## 4. Pontuação

Score de 0 a 100, **uma estimativa de risco, não uma probabilidade de incidente**. Faixas:

| Faixa | Severidade | Nível de alerta (passivo) |
|---|---|---|
| 0–24 | Baixo | Informativo |
| 25–49 | Moderado | Atenção |
| 50–69 | Alto | Alto (abre incidente) |
| 70–100 | Crítico | Crítico |

Composição: categoria mais forte (peso da categoria × confiança) + 30% das demais; mais bônus de contexto (ação de agente, conta pessoal); mais **correlações** (credencial + destino externo +10; e-mail + senha +12; dados bancários + pessoais +10; credencial + código-fonte +10; chave privada + infraestrutura +15; volume: ≥5 trechos +8, ≥10 +12; teto de +25). **Piso crítico:** credencial com confiança ≥ 0,9 vale pelo menos 75 e com ≥ 0,8 vale pelo menos 70, em qualquer texto e com qualquer peso configurado.

**Pesos por empresa:** `GET/PUT /v1/risk-weights` (admin altera, auditado; 0 a 100 por categoria; só guarda o que difere do padrão). Vale para os próximos eventos. **Ainda não há tela** para isso.

A **confiança** é a da regra, não uma probabilidade calibrada: não há dados reais de validação. Calibrar exige prompts reais revisados (a página Qualidade da detecção já coleta essa revisão).

## 5. Alertas passivos

Níveis: informativo, atenção, alto, crítico. O prompt nunca é tocado. A cadeia de alertas já existente (webhook assinado, Slack, Teams, e-mail, syslog/CEF, fila assíncrona com deduplicação; ver `docs/siem.md`) é opcional, assíncrona e não interfere no usuário. **Sistema de tickets:** só pelo webhook genérico; não há conector pronto.

## 6. Resultado padronizado (v2)

Em `output.py`, devolvido em `analysis_v2` no resultado da ingestão e no detalhe do evento. Campos: `risk_score`, `severity`, `monitoring_mode: "passive"`, `detected_categories`, `confidence`, `alert_level`, `action: "monitor"`, `masked_prompt`, `findings` (tipo, categoria, severidade, confiança, motivo, evidência **mascarada**, impacto), `reasons`, `recommendation`, `engine_version: "2.0"`. Nunca traz o valor secreto (teste varre todos os campos). A recomendação é um texto ao analista; nenhuma é executada.

```json
{"risk_score": 70, "severity": "critical", "monitoring_mode": "passive", "detected_categories": ["POSSIBLE_API_TOKEN"],
 "confidence": 0.85, "alert_level": "critical", "action": "monitor", "masked_prompt": "meu token è [TOKEN]",
 "findings": [{"type": "POSSIBLE_API_TOKEN", "category": "segredo", "severity": "critical", "confidence": 0.85,
   "reason": "Possível token ou chave informado em contexto explícito", "evidence": "[TOKEN]", "impact": "Acesso indevido a sistemas, contas ou dados..."}],
 "recommendation": "Verificar se a credencial é real e, se confirmado, avaliar sua revogação conforme o processo de resposta a incidentes da organização. Nenhuma recomendação é executada automaticamente.",
 "engine_version": "2.0"}
```

Migração 0020 guarda `findings` e `engine_version` por análise. Análises antigas ganham uma visão v2 por categoria.

## 7. Painel

- **Tabela de prompts:** data/hora, usuário, departamento, ferramenta, prompt mascarado, dados identificados, score, severidade, confiança, **status do alerta** (sem alerta, novo, em análise, falso positivo, resolvido). A coluna "Decisão" saiu.
- **Filtros:** usuário, departamento, ferramenta, categoria, severidade, período e status do alerta (também na API: `severity`, `alert_status`).
- **Detalhe:** justificativa técnica (achados, evidência mascarada, motivo, confiança, impacto, recomendação) mais o histórico de revisão já existente.
- **Indicadores:** prompts analisados, com alerta, alto risco, com dado sensível, credenciais, dados pessoais, dados financeiros, prompt injection suspeita, usuários com mais alertas, ferramentas que mais receberam dado sensível, evolução diária e mensal.
- **Pendente:** "Confirmado" como status de alerta (hoje: novo, em análise, falso positivo, resolvido); tela de pesos por empresa; histórico de análise por prompt além da revisão humana.

## 8. Testes

`packages/detection/tests/test_engine_v2.py` (os 20 cenários da especificação, em pt/en/es, mais correlação, piso, pesos, formato v2 e "o valor nunca aparece"), `apps/api/tests/test_passive_v2.py`, `packages/adapters/claude_code_hook/tests/test_passive_hook.py`, e os testes de extensão e de console em Chromium real. Conjunto de avaliação novo: `tests/fixtures/holdout_i` (96 exemplos).

Medição: `python packages/detection/scripts/compare.py --out docs/medicoes/depois.json --versus docs/medicoes/antes.json`. Métricas: exatidão, precisão, recall, taxa de falso negativo e de falso positivo (nos negativos), latência (p50/p95) e cobertura por categoria.

## 9. Comparativo antes → depois

**Leia assim:** A, B, C, E, G e **I** guiaram ajustes (otimistas). **D, F e H nunca guiaram**: são a medida honesta.

| Conjunto | Exatos | Precisão | Recall | Falso negativo | Falso positivo (negativos) | p50 / p95 ms |
|---|---|---|---|---|---|---|
| holdout_a (guiou ajuste) | 95.9% → 95.9% | 93.9% → 94.0% | 99.0% → 99.0% | 1.0% → 1.0% | 0.0% → 0.0% (0/67) | 0.35 / 0.68 |
| holdout_b (guiou ajuste) | 97.9% → 97.9% | 96.7% → 96.7% | 100.0% → 100.0% | 0.0% → 0.0% | 0.0% → 0.0% (0/80) | 0.42 / 0.88 |
| holdout_c (guiou ajuste) | 97.0% → 97.0% | 96.0% → 96.0% | 99.0% → 99.0% | 1.0% → 1.0% | 0.0% → 0.0% (0/76) | 0.41 / 0.96 |
| holdout_d (independente) | 86.2% → 86.8% | 89.7% → 89.9% | 82.4% → 83.5% | 17.6% → 16.5% | 2.9% → 2.9% (2/70) | 0.41 / 1.03 |
| holdout_e (guiou ajuste) | 96.3% → 96.3% | 97.2% → 97.2% | 98.6% → 98.6% | 1.4% → 1.4% | 0.0% → 0.0% (0/21) | 0.44 / 0.87 |
| holdout_f (independente) | 90.2% → 91.0% | 98.9% → 98.9% | 87.6% → 88.6% | 12.4% → 11.4% | 0.0% → 0.0% (0/39) | 0.45 / 0.89 |
| holdout_g (guiou ajuste) | 100.0% → 100.0% | 100.0% → 100.0% | 100.0% → 100.0% | 0.0% → 0.0% | 0.0% → 0.0% (0/22) | 0.47 / 0.65 |
| holdout_h (independente) | 91.2% → 91.2% | 100.0% → 100.0% | 86.4% → 86.4% | 13.6% → 13.6% | 0.0% → 0.0% (0/25) | 0.41 / 0.68 |
| holdout_i (guiou ajuste) | 69.8% → 100.0% | 100.0% → 100.0% | 61.3% → 100.0% | 38.7% → 0.0% | 0.0% → 0.0% (0/33) | 0.25 / 0.53 |

**Por categoria (todos os conjuntos somados):**

| Categoria | TP | FP | FN | Precisão | Recall | Coberta |
|---|---|---|---|---|---|---|
| alteracao_permissao | 20 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| arquitetura | 10 | 1 | 0 | 91% → 91% | 100% → 100% | sim |
| cliente | 22 | 0 | 2 | 100% → 100% | 92% → 92% | sim |
| codigo_proprietario | 11 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| conteudo_toxico | 22 | 0 | 1 | 100% → 100% | 96% → 96% | sim |
| envenenamento_mcp | 6 | 4 | 0 | 60% → 60% | 100% → 100% | sim |
| escrita_fora_projeto | 18 | 2 | 0 | 90% → 90% | 100% → 100% | sim |
| estrategia_ma | 20 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| exfiltracao_ferramenta | 12 | 7 | 0 | 63% → 63% | 100% → 100% | sim |
| extracao_system_prompt | 25 | 1 | 4 | 96% → 96% | 86% → 86% | sim |
| financeiro | 54 | 2 | 0 | 96% → 96% | 83% → 100% | sim |
| iac | 12 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| injection_direta | 36 | 1 | 6 | 97% → 97% | 83% → 86% | sim |
| injection_indireta | 15 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| instalacao_pacote | 7 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| jailbreak | 23 | 2 | 3 | 92% → 92% | 88% → 88% | sim |
| juridico | 26 | 1 | 1 | 96% → 96% | 96% → 96% | sim |
| leitura_env | 42 | 2 | 1 | 95% → 95% | 98% → 98% | sim |
| logs | 6 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| pii | 105 | 4 | 5 | 96% → 96% | 95% → 95% | sim |
| propriedade_intelectual | 2 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| rede_externa | 28 | 3 | 0 | 90% → 90% | 100% → 100% | sim |
| revisao_codigo | 7 | 0 | 1 | 100% → 100% | 88% → 88% | sim |
| rh | 47 | 1 | 6 | 98% → 98% | 89% → 89% | sim |
| saude | 40 | 0 | 1 | 100% → 100% | 98% → 98% | sim |
| segredo | 122 | 0 | 1 | 100% → 100% | 81% → 99% | sim |
| shell_destrutivo | 39 | 0 | 1 | 100% → 100% | 98% → 98% | sim |
| sql | 8 | 1 | 0 | 89% → 89% | 100% → 100% | sim |
| uso_pessoal | 37 | 0 | 3 | 100% → 100% | 92% → 92% | sim |

Conclusão honesta: no conjunto novo (I) o recall de segredos foi de 42% para 100%, mas ele foi escrito depois do diagnóstico, então é otimista. Nos conjuntos independentes **não houve regressão**: D subiu de 86,2% para 86,8%, F de 90,2% para 91,0%, H ficou em 91,2%. A taxa de falso positivo nos negativos difíceis não piorou (0 de 33 em I; 2 de 70 em D, como antes). Latência: p50 abaixo de 1 ms e p95 em cerca de 1 ms por prompt.

## 10. Implantação

1. Servidor: `git pull` e `bash infra/atualizar.sh` (a migração 0020 roda sozinha; faz backup antes). `PASSIVE_ONLY` não precisa ser definido: o padrão já é passivo.
2. **Reinstalar o sensor** em cada máquina (a linha do console) e **recarregar a extensão** em `chrome://extensions`: as versões antigas continuam funcionando, mas a extensão antiga ainda segura o envio até a API responder.
3. Revisar as políticas: as que estavam em "aplicar" passam a ser inertes (continuam listadas; edite para salvar como monitorar).
4. Conferir no console: selo "monitoramento passivo" e a página Todos os prompts com as colunas novas.

## 11. Riscos e limitações conhecidos

- **Sem validação com dados reais.** Precisão, recall e confiança valem para texto sintético escrito por quem escreveu as regras. Em dados reais pode ser pior.
- **Confiança de regra, não probabilidade calibrada.**
- **Regras, não semântica.** Frases sem substantivo do dicionário ("anota aí o negócio de acesso: X") passam. Erros de digitação além dos cobertos por padrão não são tolerados; espanhol cobre o dicionário escrito, não o idioma.
- **Cartão com Luhn inválido em contexto** tem confiança menor (0,6) e pode alertar um número que não era cartão.
- **Credencial genérica** (`token é X`) pode alertar um valor de teste que parece real; o analista confirma.
- **Valor simples** (`minha senha é qwertyuiop`) alerta como moderado mesmo sendo um valor de teste; a lista de palavras comuns (pt, en, es) evita `minha senha é forte`, mas é uma lista, não um dicionário: uma palavra comum fora dela vira alerta moderado.
- **Código**: o detector de "isso é código" é por padrões de linguagem; trecho curto ou em linguagem rara pode passar sem o aviso de código.
- **Mascarar não é anonimizar:** o mascaramento é heurístico; o que não for reconhecido fica no banco.
- **Passivo tem custo:** o PromptShield avisa depois do envio; um segredo enviado já chegou à ferramenta de IA.
- **Hook do Codex no Windows:** a causa do "Hook failed" não foi confirmada (ver `docs/guia-ias.md`).
- **Dois tipos de política ainda existem na tela** (ação "Bloquear" etc.), agora como o que a política *indicaria*. É vocabulário antigo; vale renomear.
- Retenção, RLS, criptografia do texto original, RBAC e auditoria **não mudaram** nesta etapa.
