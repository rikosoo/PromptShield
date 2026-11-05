# Piloto de 30 dias, só monitorar (Etapa 9)

Objetivo: mostrar ao cliente, em 30 dias e **sem bloquear ninguém**, quanto uso de IA existe, onde estão os riscos, quão confiáveis são os alertas e o que ele ganharia ligando a aplicação. Tudo roda em **modo monitorar** (princípio 7): nenhuma política é aplicada e o produto prova isso na tela do piloto e no relatório.

## Antes de ligar (checklist de instalação)

**Jurídico e pessoas** (o produto não faz isto por você; ver `docs/lgpd.md`):
- [ ] contrato de operador/processor (DPA) assinado e avaliação dos subcontratados do cliente (SMTP, Slack, SIEM)
- [ ] base legal definida e teste de legítimo interesse (LIA) escrito; RIPD/DPIA avaliado
- [ ] aviso aos colaboradores publicado (modelo na seção 6 do `docs/lgpd.md`) e política de uso de IA publicada; nos EUA, reconhecimento por escrito onde o estado exige
- [ ] representantes dos trabalhadores consultados onde a lei local exigir (**A VERIFICAR** país a país)
- [ ] encarregado (DPO) ou contato de privacidade definido para os pedidos dos titulares

**Técnico:**
- [ ] API publicada em HTTPS com certificado público atrás de um proxy reverso (o `docker-compose` do projeto não traz TLS e nunca foi executado)
- [ ] `ORIGINAL_TEXT_MASTER_KEY` gerada e guardada **fora** do banco e do backup; `docker compose` com o serviço `worker` ligado
- [ ] login do console por OIDC configurado (**nunca testado contra um provedor real**; use um provedor de homologação primeiro)
- [ ] tenant criado (`python -m app.cli create-tenant`), administrador e usuários por papel (`create-user`), chave de API do coletor com expiração
- [ ] retenção revista (padrão 90 dias; original desligado, e se ligado, 30 dias) e **categorias sem guarda de texto** conferidas (saúde marcada)
- [ ] coletores instalados por ordem de risco: hook do Claude Code (REAL, testado com Claude Code 2.1.296), extensão de navegador (EXPERIMENTAL: **nunca testada** em chatgpt.com/claude.ai), inference hooks do Claude Enterprise (PARCIAL, beta, só plano Enterprise, em **Shadow mode** nos dois lados)
- [ ] canais de alerta testados com o botão "Testar" (Teams é EXPERIMENTAL; e-mail exige SMTP)
- [ ] backup feito e **restauração testada** em banco vazio (`infra/backup.sh`, `infra/restore.sh`)
- [ ] `/metrics` ligado com token (opcional) e alguém olhando os logs
- [ ] na tela Piloto: usuários esperados informados, duração (30 dias) e **Iniciar piloto agora** clicado

## Roteiro dos 30 dias

| Dias | O que fazer | Saída |
|---|---|---|
| 1 a 3 | instalar coletores em um grupo pequeno (equipe de segurança e engenharia), conferir que os eventos chegam, ajustar domínios e aviso | primeiro alerta; primeira leitura de cobertura |
| 4 a 10 | ampliar para todos os usuários esperados; **sortear a primeira amostra de 50 eventos sinalizados** e revisá-los; ajustar dicionários e score com o que a revisão mostrar | taxa de falso positivo preliminar; lista de ajustes |
| 11 a 17 | segunda amostra; revisar incidentes reais com o cliente; testar simulações de política ("o que teria sido bloqueado") | política candidata a aplicar |
| 18 a 24 | terceira amostra; revisão do que **deveria** ter sido sinalizado e não foi (isto o produto não mede sozinho: peça exemplos ao cliente) | lista de falsos negativos conhecidos |
| 25 a 30 | fechar a revisão (pelo menos 30 itens decididos para a taxa ser estável), gerar o **relatório final**, reunião de decisão | relatório; decisão de seguir, ajustar ou parar |

## Métricas de sucesso (definições exatas, calculadas no banco)

| Métrica | Como é medida | Meta sugerida (**a combinar com o cliente**; não é padrão de mercado) |
|---|---|---|
| **Cobertura de usuários** | usuários distintos com ao menos um evento desde o início do piloto ÷ usuários esperados informados | 80% ou mais |
| **Taxa de falso positivo** | entre os itens da amostra **decididos** (verdadeiro ou falso positivo; "incerto" fica de fora), quantos o revisor humano marcou como falso positivo; mostrada com intervalo de confiança de 95% (Wilson) | 20% ou menos, e só vale com **30 ou mais itens decididos** |
| **Tempo até o primeiro alerta** | do início do piloto (ou do primeiro evento, se o início não foi marcado) até a criação do primeiro alerta | 24 horas ou menos |
| **Modo só monitorar** | todas as políticas em monitorar **e** zero decisões aplicadas no período | confirmado |

**Como ler a taxa de falso positivo, sem se enganar:**
- A amostra é **aleatória entre os eventos que o produto sinalizou** (score de 35 ou mais) e que ainda não foram amostrados; cada evento entra uma só vez.
- Ela mede quantos dos **sinalizados** estavam errados. **Não mede falsos negativos** (o que passou sem ser sinalizado). Um produto pode ter pouco falso positivo e deixar passar muita coisa.
- Com menos de 30 itens decididos, o produto avisa "amostra pequena" e mostra o intervalo, que é largo.
- A revisão é humana e subjetiva; use dois revisores em uma subamostra se o cliente quiser medir concordância (**o produto não calcula concordância entre revisores**).

## Critério para seguir para "aplicar"

Só mover uma política para **aplicar** quando: a simulação mostrar poucos eventos legítimos afetados; a taxa de falso positivo daquela categoria estiver aceitável **com amostra suficiente**; houver caminho de exceção para o usuário (política de uso, contato); e o cliente concordar por escrito. Comece pela política mais precisa (por exemplo, segredos e chaves), nunca por todas ao mesmo tempo.

## Relatório final que o cliente recebe

Tela **Piloto** > "Gerar relatório final (PDF)" (ou `POST /v1/reports` com `kind: piloto`, também em CSV; pode ser agendado). Traz: metas sugeridas e o medido (atingida, não atingida ou sem dados suficientes), cobertura por departamento e canal, falsos positivos com intervalo e aviso de amostra, tempo até o primeiro alerta, confirmação do modo monitorar, categorias mais frequentes, incidentes por status, alertas por regra e os limites do relatório. **Os números vêm das mesmas consultas do painel** (teste: `test_pilot_report_numbers_match_the_summary`). A análise e as recomendações são do consultor: o PDF não escreve conclusões por você.

## Fora do escopo do piloto

Aplicar bloqueios; automação de resposta; qualquer decisão sobre pessoas com base no indicador de risco (ele "requer revisão humana"); medir falsos negativos sem exemplos do cliente; contas pessoais fora da organização.

## Honestidade para dizer ao cliente

1. A extensão de navegador e os inference hooks **nunca foram testados contra os serviços reais**; só o hook do Claude Code foi exercitado em um Claude Code de verdade.
2. A resposta do modelo **não passa** pelo hook do Claude Enterprise; imagens não são inspecionadas.
3. O detector é por regras e dicionários, sem modelo treinado; pode errar nos dois sentidos.
4. Texto livre sensível só é omitido nas categorias marcadas; o produto não promete achar todo dado sensível.
5. Não há certificação de conformidade; a documentação jurídica é modelo para revisão de advogado.
