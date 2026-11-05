# Privacidade: LGPD, GDPR e EUA (Etapa 9)

> **Isto não é parecer jurídico.** É um mapa técnico dos dados e um conjunto de **modelos** para um advogado revisar. A base legal, o aviso aos colaboradores, a política de uso de IA e os relatórios de impacto dependem do país, do contrato, do setor e dos fatos de cada cliente. Onde não consegui confirmar o texto de uma norma, está escrito **A VERIFICAR**. Fontes e datas no fim.

## 1. Quem é quem

| Papel | LGPD | GDPR | CCPA/CPRA (Califórnia) |
|---|---|---|---|
| Empresa cliente, que decide usar o produto sobre seus colaboradores | controlador | controller | business |
| PromptShield (quem opera o produto para o cliente) | operador | processor (Art. 28) | service provider |
| Pessoas monitoradas (colaboradores e agentes que usam IA) | titulares | data subjects | consumers (empregados estão cobertos, **A VERIFICAR** o texto vigente) |

Consequência: o cliente decide a finalidade e a base legal, fala com os titulares e responde à autoridade; **é preciso um contrato de operador/processor (DPA)** entre o cliente e quem opera o produto, com as instruções de tratamento, subcontratados, medidas de segurança e prazos de aviso de incidente. O produto **não** é "compliance certificada": não há ISO 27001, SOC 2 nem auditoria externa.

## 2. Mapa de dados (o que o código realmente guarda)

| Dado | De quem | Finalidade | Onde | Retenção | Cifrado? | Quem acessa |
|---|---|---|---|---|---|---|
| Texto do prompt, resposta ou ação do agente, **com identificadores mascarados** (e omitido nas categorias marcadas, saúde por padrão) | colaborador | detectar risco e permitir revisão humana | `events.masked_text` | `retention_days` (padrão 90) | em repouso: não (só o banco) | admin, analista, auditor, leitura (console) |
| Identificador do usuário (e-mail ou id), departamento, ferramenta, canal, sessão, horário | colaborador | atribuir uso e risco | `events` | idem | idem | idem |
| Categorias, score, motivos, decisão, trechos mascarados | derivado | explicar o risco | `analyses` | idem (apaga com o evento) | idem | idem |
| Incidentes e alertas | derivado | triagem | `incidents`, `alerts` | idem | idem | idem |
| **Texto original** | colaborador | só se o tenant ligar (`store_original`); desligado por padrão | `events.original_ciphertext` | `original_retention_days` (padrão 30, nunca maior que a retenção geral) | **sim** (chave de dados por tenant, embrulhada pela chave mestra) | admin e analista, com justificativa e auditoria |
| Justificativa de leitura do original, status de incidente | usuário do console | rastreabilidade | `audit_log` | **sem apagamento automático** (imutável) | não | admin e auditor |
| Usuários do console (e-mail, papel, departamento) | equipe de segurança | autenticação e papéis | `users` | até o administrador removê-los (`DELETE /v1/users/{id}`); a auditoria guarda só o UUID | não | admin |
| Relatórios gerados (PDF/CSV) | agregados; o executivo lista um ranking com identificadores | prestação de contas | `reports` | `retention_days` | não | admin, analista, auditor |
| Registros das requisições dos inference hooks | — | medir tempo e veredito | `inference_hook_requests` | `retention_days` | **sem conteúdo** | admin, analista, auditor (agregados) |
| Revisões do piloto (rótulo certo/errado) | revisor | medir falso positivo | `pilot_reviews` | apaga com o evento | não | admin, analista |
| Segredos de canais, URLs de webhook, segredo de assinatura dos hooks | cliente | operar integrações | colunas `*_ciphertext` | até o cliente remover | **sim** | só a aplicação |
| Chaves de API | cliente | autenticar coletores | `api_keys` | até revogar/expirar | só o hash SHA-256 | — |

**Dados sensíveis (LGPD art. 5º, II e art. 11; GDPR art. 9).** O produto não pede nem procura esses dados, mas **um colaborador pode digitar** saúde, filiação sindical, origem racial etc. em um prompt. O que o código faz, sem exagero:
- O **mascaramento** substitui **identificadores estruturados** (CPF, CNPJ, RG, cartões, e-mail, telefone, chaves e segredos). **Texto livre sensível não é mascarado**: o motor *classifica* (por exemplo "saúde"), mas o diagnóstico digitado ficaria no texto guardado.
- Por isso o tenant tem a lista `omit_text_categories` (padrão: **saúde**): quando o motor detecta uma dessas categorias (confiança de 0,5 ou mais), o evento guarda o aviso `[texto não guardado: categoria ...]` no lugar do texto. O evento continua classificado e pontuado, e o original cifrado só existe se o cliente ligou `store_original`. Qualquer categoria da taxonomia pode ser marcada (tela Privacidade e segurança). Prova: `test_health_text_is_not_stored_by_default_but_is_still_classified`.
- **Limite:** a omissão depende de o motor detectar a categoria; o detector de saúde é por regras e dicionários e **pode falhar** (o relatório `docs/relatorio-etapa2.md` mostra as taxas medidas em dados sintéticos). Categorias sensíveis que o motor não tem (como filiação sindical) **não são reconhecidas**. As demais categorias (RH, jurídico, cliente...) só têm omissão se o cliente as marcar.

**O que NÃO é guardado:** captura de tela, teclas digitadas, histórico de navegação, conteúdo fora dos domínios e ferramentas configurados, conversa com contas pessoais fora da organização (os inference hooks só cobrem a organização Enterprise).

**Fluxos para fora do produto (todos configurados pelo cliente):** notificações por webhook, Slack, Teams, e-mail e syslog (só metadados, nunca o texto do prompt), exportação para SIEM (idem), e o cliente que usar os inference hooks está enviando as conversas **da Anthropic para o servidor do PromptShield**. Nenhum conteúdo de cliente vai para modelo de linguagem externo (princípio do projeto; a classificação roda localmente).

## 3. Bases legais sugeridas (para o advogado confirmar)

**Brasil (LGPD).** Consentimento (art. 7º, I) é frágil na relação de trabalho (a recusa tem consequência). A base mais citada para monitoramento de segurança é o **legítimo interesse (art. 7º, IX, com art. 10)**, que exige finalidade legítima, **necessidade e proporcionalidade** e o teste de que os direitos do titular não prevalecem; outras bases podem aplicar a obrigações legais ou regulatórias do setor (art. 7º, II). Comentários jurídicos que li (não a ANPD) apontam que, para monitoramento de empregados, é preciso demonstrar por que a medida é necessária e menos invasiva que alternativas. Para dados sensíveis incidentais, o art. 11 precisa de avaliação própria. Registre as operações (art. 37) e avalie um **relatório de impacto (RIPD, art. 38)**: a recomendação de fazê-lo para sistemas potencialmente invasivos vem de comentário jurídico, **não** de obrigação confirmada da ANPD (**A VERIFICAR**).

**União Europeia (GDPR).** Consentimento no trabalho é, em regra, inválido por desequilíbrio de poder (WP29, Opinion 2/2017). A base usual é o **interesse legítimo (Art. 6(1)(f))** com teste de balanceamento documentado, necessidade estrita, proporcionalidade e subsidiariedade, e **transparência efetiva** ao empregado. **O Art. 88** permite que cada Estado-membro (ou acordos coletivos) tenha regras específicas para dados de empregados. Em vários países há consulta ou acordo com **representantes dos trabalhadores** antes de instalar ferramentas de monitoramento: **A VERIFICAR país a país**. Uma **avaliação de impacto (DPIA, Art. 35)** é provável (monitoramento sistemático de pessoas em situação de vulnerabilidade, como empregados); confirme na lista da autoridade nacional (Art. 35(4)), que eu não consegui consultar. A opinião do WP29 alerta contra pacotes de monitoramento que capturam teclas e telas: o PromptShield não faz isso, mas o argumento da proporcionalidade continua sendo do cliente.

**Estados Unidos.** Não há lei federal geral de privacidade; o que existe é um mosaico:
- **Wiretap Act / ECPA (18 U.S.C. § 2511)**: as exceções que empregadores costumam usar são o **consentimento** e o uso comercial normal; o consentimento por **reconhecimento escrito** do empregado é a forma mais segura. A exceção não vale para finalidade criminosa ou ilícita. O que li veio de guias, não do texto da lei: **A VERIFICAR**.
- **Aviso prévio obrigatório em alguns estados:** **Nova York** (Civil Rights Law § 52-c, em vigor desde 7/5/2022): aviso por escrito na contratação, reconhecimento do empregado e afixação em local visível; multa civil de até US$ 500 na primeira infração, US$ 1.000 na segunda e valores maiores nas seguintes; fiscalizada pelo Procurador-Geral. **Connecticut** (Conn. Gen. Stat. § 31-48d) e **Delaware** (19 Del. C. § 705) também exigem aviso (Delaware oferece duas formas: aviso eletrônico a cada acesso ou aviso único com reconhecimento). **As multas citadas em fontes divergem entre si e eu não li os textos oficiais: A VERIFICAR**.
- **Califórnia (CCPA/CPRA):** a lei cobre dados de empregados e candidatos; exige **aviso na coleta** (**A VERIFICAR** o texto vigente; a informação sobre a regra de 2023 veio de conhecimento geral, não de fonte lida). Os regulamentos da CPPA sobre **avaliação de riscos e decisões automatizadas (ADMT)** entraram em vigor em 1/1/2026, com obrigações de ADMT a partir de 1/1/2027 e avaliações de riscos de tratamentos anteriores a 2026 até 31/12/2027 (fonte: resumos de escritórios de advocacia, 2026). **O score do PromptShield é um indicador para revisão humana e foi projetado para não ser usado como única base de uma decisão sobre emprego; se o cliente o usar para decisões relevantes de emprego, as regras de ADMT podem se aplicar: A VERIFICAR com o advogado.**
- **Dados regulados por setor:** se prompts puderem conter informação de saúde de pacientes (HIPAA) ou dados financeiros de clientes (GLBA), o cliente precisa de acordos próprios (por exemplo um BAA). O produto mascara antes de guardar, mas o texto **passa** pelo servidor do PromptShield antes de ser mascarado.
- Outras leis estaduais de privacidade e de IA em emprego estão em mudança (por exemplo Colorado): **A VERIFICAR**; não consegui confirmar o estado atual.

## 4. Direitos dos titulares e o que o produto faz

| Direito | LGPD (art. 18) | GDPR | CCPA | No produto |
|---|---|---|---|---|
| Confirmar e acessar | I, II | Art. 15 | saber | `GET /v1/privacy/subject?user_id=` (admin e auditor): eventos mascarados, contagem de incidentes e alertas; o original nunca sai por essa rota. Console: Privacidade e segurança. |
| Eliminar | VI | Art. 17 | excluir | `POST /v1/privacy/subject/erase` (só admin, justificativa obrigatória): apaga eventos, análises, incidentes, alertas e notificações na fila da pessoa; a auditoria guarda **só o hash** do identificador. Relatórios executivos já gerados podem citar a pessoa: a resposta avisa quantos revisar e `DELETE /v1/reports/{id}` os apaga. |
| Portabilidade | V | Art. 20 | — | a consulta devolve JSON; formato próprio, não padronizado. |
| Corrigir | III | Art. 16 | corrigir | **não se aplica ao texto capturado** (é um registro do que foi digitado). Uma classificação contestada pode ser marcada "falso positivo" no incidente. |
| Oposição e restrição | — (art. 18, §2º) | Arts. 18 e 21 | limitar uso de dado sensível | **não implementado**: hoje a pessoa só deixa de ser monitorada se o cliente tirar o coletor dela ou ajustar o escopo da política. Pendente. |
| Revisão de decisão automatizada | art. 20 | Art. 22 | ADMT (2027) | o score nunca é a única base: a interface diz "indicador de risco, requer revisão humana"; as políticas nascem em modo só monitorar; bloquear é opção do cliente, por política. |
| Informação sobre compartilhamento | VII | Arts. 13/14 | — | a seção 2 e o aviso (seção 6) listam os destinos; o cliente configura os canais. |

Prazos de resposta variam (por exemplo, o GDPR dá um mês em regra, o art. 19 da LGPD tem prazos próprios e a Califórnia 45 dias): **confirme com o advogado**. Quem recebe e responde os pedidos é o **cliente**; o produto é a ferramenta. Não há fila de pedidos nem verificação de identidade do titular no produto.

**Eliminação e backup:** um backup restaurado **traz de volta** dados já eliminados. Mantenha o registro dos pedidos de eliminação fora do banco e reaplique-os depois de restaurar (`docs/operacao.md`).

## 5. Retenção e minimização (princípios implementados)

- Guarda do texto com identificadores **mascarados** por padrão e **omitido** nas categorias marcadas (saúde); o original é opt-in, cifrado e apagado mais cedo (padrão 30 dias; nunca depois da retenção geral).
- Retenção configurável por tenant (padrão 90 dias, 7 a 365), executada pelo worker uma vez por dia e sob demanda; cada execução grava contagens na auditoria. Prova: `test_retention_deletes_what_expired_and_only_that`.
- A auditoria **não** tem apagamento automático: é imutável por desenho, não leva texto de prompt, e o registro guarda só UUIDs (a remoção de um usuário do console anonimiza a trilha). **Decisão a validar com o advogado:** prazo de guarda do registro de auditoria (base: obrigação legal ou legítimo interesse de segurança). Hoje, apagá-lo exige mexer no banco como dono.
- Pseudonimização do identificador do usuário **não existe**: o console mostra o identificador enviado pelo coletor. Pendente (opção por tenant).

## 6. Modelo de aviso ao colaborador (**modelo, a ser revisado por advogado**)

> **Aviso sobre o uso de ferramentas de IA**
> A [EMPRESA] monitora o uso de ferramentas de inteligência artificial **fornecidas ou autorizadas pela empresa** ([lista: Claude Code, Claude, ChatGPT no navegador da empresa, ...]) para proteger dados pessoais, segredos e propriedade intelectual e para cumprir a lei.
> **O que é coletado:** o texto que você envia a essas ferramentas e as ações que agentes de IA executam em seu nome, com seu identificador, departamento, ferramenta e horário. O texto é **mascarado** (CPF, cartões, chaves, etc. são substituídos) antes de ser guardado. [Se ligado: o texto original é guardado cifrado por até N dias e só é lido com justificativa registrada.]
> **O que não é coletado:** teclas digitadas fora das ferramentas, capturas de tela, navegação em outros sites, contas pessoais fora da organização.
> **Quem vê:** a equipe de segurança [e analistas designados]. Os indicadores de risco **exigem revisão humana** e não são prova de má conduta nem a única base para decisões sobre você.
> **Por quanto tempo:** [90] dias.
> **Seus direitos:** acesso, eliminação e demais direitos da lei aplicável, pelo contato [ENCARREGADO/DPO: e-mail]. [Para colaboradores nos EUA: conteúdo exigido pela lei do estado, com **reconhecimento por escrito ou eletrônico**.]
> **Contas pessoais:** não use ferramentas pessoais para dados da empresa; o monitoramento não alcança contas pessoais fora da organização.
> [Base legal, controlador e contato conforme o advogado. Em países que exigem, o texto foi apresentado aos representantes dos trabalhadores.]

A extensão de navegador mostra um aviso ao usuário e pode apontar para a política de uso do tenant (`policy_url`).

## 7. Modelo de política de uso de IA (**modelo, a ser revisado por advogado**)

1. **Escopo:** vale para todo colaborador e prestador que use ferramentas de IA no trabalho.
2. **Ferramentas permitidas:** [lista]. Ferramentas não listadas exigem aprovação de [área].
3. **Contas:** use a conta corporativa. Não use conta pessoal para dados da empresa.
4. **O que nunca enviar:** credenciais, chaves e segredos; dados pessoais de clientes ou colaboradores sem necessidade; dados de saúde; código proprietário em ferramentas não aprovadas; informação sob sigilo ou sob ordem judicial.
5. **Agentes de IA:** só com permissões mínimas; ações destrutivas e leitura de credenciais podem ser bloqueadas conforme a política.
6. **Monitoramento:** descrito no Aviso (seção 6), incluindo mascaramento, prazos e direitos.
7. **Resposta:** o alerta pede **revisão humana**. Nenhuma medida disciplinar se baseia só no indicador de risco.
8. **Dúvidas e incidentes:** contato [segurança] e [encarregado/DPO]; comunique vazamentos acidentais de dados imediatamente.
9. **Revisão:** esta política é revista a cada [12] meses.

## 8. Incidentes de segurança

- **LGPD (art. 48) e Resolução CD/ANPD nº 15/2024:** comunicação à ANPD e aos titulares em **três dias úteis** a partir do conhecimento de que o incidente afetou dados pessoais, quando houver risco ou dano relevante; informações complementares em até 20 dias úteis (fonte: resumos de escritórios de advocacia e um fórum do CERT.br; um blog cita prazo em dobro para agentes de pequeno porte, **não confirmado**: leia o texto oficial).
- **GDPR (Arts. 33 e 34):** notificação à autoridade em até **72 horas** da ciência (quando houver risco), e aos titulares se o risco for alto. **O processor avisa o controller sem demora injustificada (Art. 33(2))**: isso entra no DPA. (Conhecimento geral do texto do GDPR; não reabri a norma.)
- **EUA:** leis estaduais de notificação de violação variam: **A VERIFICAR** por estado.
- O que o produto ajuda a fazer: auditoria imutável, `GET /v1/audit-log`, métricas e logs sem conteúdo para investigar sem ampliar o vazamento, `GET /v1/privacy/data-map` para dimensionar quais dados e quantas pessoas estão no tenant. **Não existe** um fluxo de resposta a incidentes nem aviso automático à autoridade.

## 9. Transferência internacional

- **LGPD (arts. 33 a 36):** transferência exige um mecanismo legal (adequação, cláusulas, etc.); a regulamentação de cláusulas padrão pela ANPD é **A VERIFICAR**.
- **GDPR (Capítulo V):** o **EU-US Data Privacy Framework** está em vigor (o Tribunal Geral manteve a decisão de adequação em 3/9/2025; há recurso pendente no TJUE, caso C-703/25 P; última notícia lida: junho de 2026). Cláusulas contratuais padrão são a alternativa se o quadro cair (fonte: resumos de escritórios de advocacia; **A VERIFICAR** o andamento).
- **O produto não decide onde roda:** a nuvem de produção ainda não foi escolhida (CLAUDE.md). Residência de dados por tenant **não existe** (pendente). O cliente precisa saber em que país o banco e o backup ficam.

## 10. Registro de operações (ROPA), RIPD e DPIA: esqueleto pré-preenchido

**Registro de operações (LGPD art. 37, GDPR Art. 30)**, o que o produto permite preencher: finalidade (segurança da informação e conformidade no uso de IA); categorias de titulares (colaboradores, prestadores, agentes de IA operando em nome deles); categorias de dados (seção 2); destinatários (equipe de segurança do cliente; destinos de alerta/SIEM que o cliente configurar); transferências (seção 9); prazos (seção 5); medidas de segurança (`docs/ameacas.md`).

**RIPD/DPIA, itens a descrever pelo cliente com o advogado:** (1) descrição do tratamento e da finalidade; (2) **necessidade e proporcionalidade**: por que monitorar, que alternativas menos invasivas foram consideradas (treinamento, bloqueio de ferramentas, DLP sem identificar pessoas), por que o escopo é limitado a ferramentas e domínios configurados; (3) riscos para os titulares: identificar pessoas pelo uso de IA, dado sensível digitado por engano, uso indevido do indicador de risco, vazamento; (4) medidas: mascaramento por padrão, original opt-in e cifrado com prazo curto, retenção, papéis, auditoria, modo só monitorar, revisão humana, avisos; (5) consulta aos titulares ou representantes, quando exigida; (6) risco residual e aprovação.

**Teste de legítimo interesse (LIA)**, em três perguntas: o interesse é legítimo e específico? O tratamento é necessário para ele, sem alternativa menos invasiva? O resultado do balanceamento, considerando as expectativas razoáveis do colaborador e as salvaguardas acima, favorece o tratamento?

## 11. O que o produto NÃO faz (para não prometer demais)

Coletar consentimento; fila e verificação de identidade para pedidos de titulares; oposição e restrição; suspensão por obrigação legal (legal hold); pseudonimização do identificador no console; residência de dados; aviso automático à autoridade; apagamento automático da auditoria; detecção confiável de todas as categorias sensíveis do art. 11/Art. 9 (e o que o detector não reconhece fica guardado no texto); certificação ou auditoria externa de conformidade.

## 12. Fontes e o que ficou sem confirmação

Lidas por busca em 2026-10-15 (resumos de terceiros; **os textos oficiais não foram abertos**, os domínios não resolvem neste ambiente): [Resolução CD/ANPD nº 15/2024](https://www.mattosfilho.com.br/unico/regulamento-incidente-seguranca/) e [Lefosse](https://lefosse.com/noticias/alerta/client-alert-anpd-aprova-regulamento-de-comunicacao-de-incidente-de-seguranca/); [WP29 Opinion 2/2017](https://gdpr-text.com/en/guidelines/dataprocessingatwork/) e [resumo](https://www.rpc.co.uk/snapshots/data-protection/data-protection-working-party-adopts-opinion-22017-on-data-processing-at-work); [NY Civil Rights Law § 52-c](https://newyork.public.law/laws/n.y._civil_rights_law_section_52-c*2) e [resumo](https://www.mofo.com/resources/insights/211115-new-york-enacts-employee-monitoring-notification-law); [Connecticut DOL](https://portal.ct.gov/dol/-/media/DOL/2022-New-Design-System/Divisions/wage-and-workplace-standards/ElectronicMonitoring.pdf); [regulamentos CPPA (ADMT, avaliação de riscos)](https://www.thompsoncoburn.com/insights/californias-2026-ccpa-regulations-summary-and-preparation-guide/); [Data Privacy Framework e recurso Latombe](https://www.wilmerhale.com/en/insights/blogs/wilmerhale-privacy-and-cybersecurity-law/20251201-european-court-of-justice-to-review-challenge-to-eu-us-data-privacy-framework).

**Sem confirmação em fonte:** texto dos arts. 7º, 10, 11, 18, 19, 37, 38 e 48 da LGPD e dos Arts. 6, 9, 13 a 22, 28, 30, 33 a 35, 44 a 49 e 88 do GDPR (citados pela numeração que conheço; confira); lista nacional de DPIA; ECPA (texto e exceções); multas de Connecticut e Delaware; regras de aviso do CCPA para empregados; leis estaduais de IA no emprego; regras de consulta a representantes de trabalhadores por país; notificação de violação nos estados americanos.
