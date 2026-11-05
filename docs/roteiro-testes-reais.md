# Roteiro de testes reais

Tudo que o PromptShield fez até aqui foi testado com dados sintéticos e entradas simuladas. Este roteiro leva cada integração a um serviço real, na ordem de menor para maior risco, e define quando uma integração pode sair de PARCIAL para REAL (princípio 1). Nenhum item abaixo foi executado ainda; cada um nasce **NÃO EXECUTADO**.

Regras para todos os testes:

- Dados sintéticos e rotulados como simulados (princípio 5). Contas de teste, nunca contas de funcionários em produção.
- Política em modo sombra (princípio 7) até o passo explicitamente dizer o contrário, e só em tenant de teste.
- Coleta transparente, com aviso ao usuário de teste (princípio 2).
- Nenhum segredo real no repositório nem no registro de evidências: guardar valores só no cofre do responsável, e no registro apenas "ok" ou o identificador.
- Documentação de terceiros relida na data do teste; se mudou, registrar a versão e a data. O que não der para verificar fica **A VERIFICAR**.

## Ordem e dependências

| # | Teste | Depende de | Duração estimada | Responsável |
|---|---|---|---|---|
| 0 | Ambiente: `docker compose` com TLS | máquina com Docker, domínio de teste | 0,5 dia | engenharia |
| 1 | Claude Code (lacunas do hook) | 0, Claude Code ≥ 2.1.295 | 0,5 dia | engenharia |
| 2 | OIDC com IdP de homologação | 0, conta de teste no IdP | 1 dia | engenharia + TI |
| 3 | Extensão em chatgpt.com e claude.ai | 0, 2, contas de teste | 1 dia | engenharia |
| 4 | Inference hooks com tenant Claude Enterprise real | 0, 2, tenant de teste | 1 a 2 dias | engenharia + dono do tenant |
| 5 | Canais de alerta e SIEM | 0 | 0,5 dia | engenharia + SecOps |
| 6 | Carga e dimensionamento | 0 | 0,5 dia | engenharia |
| 7 | Backup e restauração | 0 | 0,5 dia | operação |
| 8 | Teste de invasão externo | 0 a 7 verdes | 1 a 2 semanas | terceiro |
| 9 | Portões jurídicos | em paralelo desde o início | semanas | jurídico/DPO |

Estimativas são palpites de planejamento, não medições.

## Modelo de cada passo

Cada passo deve ser registrado no [registro de evidências](#registro-de-evidências) com: data, versão do commit, versão do produto de terceiro, quem executou, resultado (passou, falhou, parcial), evidência (captura de tela sem dados reais, trecho de log, id do evento) e desvios.

---

## 0. Ambiente base (`docker compose` + TLS)

O `docker compose` nunca foi executado de ponta a ponta por falta de Docker no ambiente de desenvolvimento.

Passos:

1. `make setup` (cria o `.env` a partir de `.env.example`), preencher os segredos no `.env` (fora do git) e rodar `make up`.
2. Colocar um proxy reverso com TLS na frente da API e do console (o que `docs/operacao.md` descreve; escolha de produto em aberto).
3. As migrações rodam na subida da API (`alembic upgrade head` no `CMD` do Dockerfile). Para dados sintéticos use `seed-demo` (ver `README.md` e `apps/web/README.md`) e abra o console.

Observar: serviços saudáveis, `/health` e `/metrics` respondendo, migrações até a 0009, cookie com `Secure` atrás do TLS, cabeçalhos de segurança presentes.

Passa se: um único comando sobe tudo, o login mock funciona e `make test-e2e-web` passa contra esse ambiente. Falha registra o erro e a correção entra em `docs/operacao.md`.

Reversão: `docker compose down -v`.

## 1. Claude Code: lacunas do hook

Hoje PARCIAL. Não testados no Claude Code real: `PostToolUse`, `permissionDecision: "ask"`, sessão interativa, entrega por `managed-settings.json` ou MDM, Windows e `onFailure: "block"` (ver `docs/claude-code-hooks.md`). Reler essa página oficial antes de começar e anotar a versão.

| Caso | Como | Esperado |
|---|---|---|
| Sessão interativa | `claude` interativo com o hook instalado, enviar prompt sintético com CPF de teste | evento chega com `source.app=claude_code`, texto mascarado |
| `PostToolUse` | executar uma ferramenta de leitura de arquivo sintético com segredo falso | `tool_result` chega e é classificado |
| `ask` | política que pede confirmação | Claude Code mostra o pedido ao usuário e respeita a resposta |
| Bloqueio | política `enforce` de teste para `rm -rf /` em diretório descartável | comando não executa; motivo exibido |
| API fora do ar | derrubar a API e repetir | com `failure_mode` aberto o comando segue e o hook registra o erro local; com `onFailure: "block"` o comando é bloqueado |
| Timeout | atrasar a API além do limite do hook | comportamento igual ao documentado (não bloqueia sem `onFailure`) |
| Entrega gerenciada | colocar o hook em `managed-settings.json` | usuário não consegue desligar pelas configurações de usuário (anotar o que a documentação diz e o que se observou) |
| Windows | repetir o caso interativo e o de bloqueio em Windows 11 | mesmo resultado; anotar diferenças de caminho e de shell |

Passa se todos os casos concordam com a documentação. Cada caso que passar remove a respectiva ressalva em `docs/claude-code-hooks.md`; a integração só vira REAL quando a lista inteira passar nos sistemas que formos declarar como suportados.

## 2. OIDC com IdP de homologação

`AUTH_MODE=oidc` nunca rodou contra um provedor real; só o modo mock foi testado. Usar um IdP de teste (por exemplo um tenant de desenvolvimento do provedor que o piloto vai usar) com usuários sintéticos.

| Caso | Esperado |
|---|---|
| Login completo com PKCE | volta ao console, cookie httpOnly com `Secure` e `SameSite` |
| `issuer` incorreto ou `audience` incorreto | token recusado |
| `email_verified=false` | acesso recusado |
| Usuário sem convite/perfil | nenhum acesso e nenhum tenant criado |
| Papéis (admin, analista, leitor) | iguais à matriz de `test_security.py` |
| Expiração do token e logout | sessão encerrada, rota protegida volta ao login |
| Rotação de chaves do IdP (JWKS) | novo `kid` aceito sem reiniciar; `kid` removido recusado |
| Relógio com desvio | tolerância documentada, sem aceitar token expirado há muito tempo |
| Token de outro tenant | recusado (RLS e vínculo de usuário) |

Passa se todos os casos acima concordam. Registrar quais claims o provedor realmente entrega (nomes e formatos); onde diferirem do que o código espera, corrigir o código, não o teste.

## 3. Extensão em chatgpt.com e claude.ai

Hoje PARCIAL, e os seletores dependem do HTML das páginas, que muda sem aviso. Usar contas de teste do próprio laboratório e prompts sintéticos. Reler as políticas de uso das duas ferramentas antes (a extensão só observa o campo de texto onde o usuário digita, nos domínios configurados, com aviso visível).

| Caso | Esperado |
|---|---|
| Enviar com Enter, com o botão e com colar texto | cada um gera um evento por envio, sem duplicata |
| Texto com CPF/segredo de teste em modo `mask` | campo é reescrito com o texto mascarado sem quebrar o editor (ProseMirror em ambas); se não for possível, cai para aviso e registra |
| Anexo de arquivo | evento `file_upload` com nome e tamanho, sem conteúdo (o que a extensão faz hoje) |
| Conta pessoal vs corporativa | `context.personal_account` correto |
| Domínio fora da lista do administrador | nada é capturado |
| API fora do ar | comportamento do modo configurado (aberto ou fechado), sem travar a página |
| Instalação gerenciada (Chrome/Edge) | política do administrador instala a extensão e fixa a lista de domínios; usuário vê o aviso |
| Mudança de HTML | introduzir seletor quebrado de propósito: a extensão deve parar de capturar e avisar, nunca capturar em outro lugar |

Passa se cada caso se comporta como acima em Chrome e Edge nas versões estáveis do dia. Qualquer atualização da ferramenta que quebre seletores reduz a integração de volta a PARCIAL até nova rodada. Recomendado repetir mensalmente enquanto durar o piloto.

## 4. Inference hooks com um tenant Claude Enterprise real

Hoje PARCIAL: formato lido na documentação e testado só com chamadas simuladas. Precisa de um tenant de teste com permissão de configurar o hook. Reler `docs/inference-hooks.md` e a página oficial na data do teste.

| Caso | Esperado |
|---|---|
| Botão "Test connection" do produto | resposta aceita; assinatura validada (Standard Webhooks) |
| Origem das requisições | IP dentro do intervalo documentado (A VERIFICAR a faixa vigente; a última lida foi 160.79.106.0/24) |
| Prompt real de teste | evento `prompt` chega em sombra; nenhuma decisão de bloqueio |
| Chamada de ferramenta | quadro `tool_call` recebido e classificado |
| Conversa longa | escopo `latest` evita duplicar blocos já vistos |
| Correlação | `reference_id` do nosso evento bate com o Activity Feed do produto |
| Latência | medir p50 e p95 reais; confirmar que ficam abaixo do orçamento de 3 s e do limite documentado |
| Tamanho de corpo | enviar conversa grande; confirmar o limite de corpo e o comportamento no excesso |
| Falha da API | com `failure_mode` configurado, comportamento correto; confirmar o que o produto faz em timeout e erro |
| Circuit breaker | forçar erros em sequência; breaker abre e fecha como em `docs/inference-hooks.md` |
| Voz | confirmar se há cobertura de modo de voz (suspeita: não) e registrar a lacuna |
| Enforce | só depois de tudo acima, em um grupo de teste: política `enforce` nega uma conversa sintética e o usuário vê o motivo |

Passa se todos os casos acima concordam e o modo `enforce` foi validado em grupo de teste. Só então o status muda para REAL, com a data e a versão da documentação.

## 5. Canais de alerta e SIEM

Cada canal foi testado só contra servidores simulados.

| Canal | Teste |
|---|---|
| Webhook com HMAC | receptor real valida a assinatura; reenvio idempotente por chave |
| Slack | mensagem aparece no canal de teste; revogar o webhook e ver a falha registrada, sem perder alerta (fila) |
| Teams | **EXPERIMENTAL**: ler a documentação atual de Workflows, confirmar o formato do payload, testar e registrar |
| SMTP | STARTTLS com um servidor real de teste; falha de certificado deve recusar o envio |
| SIEM (CEF + syslog) | receptor real (o SIEM do piloto ou um coletor aberto) interpreta os campos; conferir enquadramento TCP/TLS e UDP |
| SSRF | tentar cadastrar URL para IP privado e para redirecionamento: recusado |

Passa se cada canal entrega e o receptor interpreta sem ajuste manual.

## 6. Carga e dimensionamento

Objetivo: escolher os limites de taxa com dados, não por palpite. Rodar `apps/api/scripts/bench_inference_hook.py` e um gerador de eventos contra o ambiente do passo 0, com crescimento gradual até a saturação.

Registrar: eventos por segundo sustentados, p95 de ingestão, uso de CPU e de conexões do banco, ponto de saturação, comportamento do limitador de taxa. Passa se o p95 de ingestão fica abaixo da meta com a carga prevista para o piloto mais folga de 3 vezes; senão, ajustar e repetir.

## 7. Backup e restauração

Rodar `infra/backup.sh` e `infra/restore.sh` em um ambiente limpo, com os dados do passo 0. Conferir: tabelas e contagens, política de linha por tenant continua valendo, trilha de auditoria íntegra, chaves por tenant ainda decifram os originais (e a chave mestra é guardada separadamente). Cronometrar a restauração e registrar. Passa se a restauração completa cabe no tempo que o piloto aceitar e o teste de isolamento por tenant passa depois dela.

## 8. Teste de invasão externo

Só depois dos passos 0 a 7 verdes. Escopo sugerido: API, console, BFF, extensão, rotas de hook, autenticação por chave de API, isolamento entre tenants, SSRF dos canais, exposição de texto original. Entregar ao terceiro o modelo de ameaças (`docs/ameacas.md`) e acesso a dois tenants de teste. Critério: nenhum achado crítico ou alto em aberto; médios com plano e prazo.

## 9. Portões jurídicos (em paralelo)

Os documentos `docs/lgpd.md` e correlatos são modelos para revisão de advogado, não parecer. Antes de qualquer dado de empregado real:

- Revisão por advogado de privacidade (LGPD; GDPR e leis dos EUA se houver empregados nesses locais).
- Contrato de tratamento de dados (DPA) com o cliente piloto e lista de suboperadores.
- Avaliação de legítimo interesse e relatório de impacto (RIPD/DPIA), com consulta ao encarregado (DPO).
- Aviso aos empregados aprovado, política de uso de IA atualizada e, onde exigido, consulta a sindicatos ou conselhos de trabalhadores.
- Definição de retenção e de quem pode ver o texto original, com justificativa.

Passa se cada item tem responsável, data e documento assinado. Sem isso, o piloto fica restrito a dados sintéticos.

---

## Critérios para promover `integration_status`

| Integração | De | Para | Condição |
|---|---|---|---|
| Claude Code hook | PARCIAL | REAL | passo 1 inteiro, nos sistemas declarados |
| Inference hook | PARCIAL | REAL | passo 4 inteiro, incluindo `enforce` em grupo de teste |
| Extensão (chatgpt.com, claude.ai) | PARCIAL | REAL por site | passo 3 inteiro naquele site e naquela versão do navegador |
| Teams | EXPERIMENTAL | PARCIAL | payload confirmado na documentação atual e entrega real |
| OIDC | não testado | homologado por provedor | passo 2 inteiro com aquele provedor |

Regras: a promoção é por integração e por versão testada, com data. Mudança no produto de terceiro que quebre um caso devolve a integração a PARCIAL até nova rodada. A mudança de status sai no código (`integration_status`), na documentação e em `docs/decisoes.md` no mesmo commit.

## Medição do motor de detecção em dados do cliente

A estimativa atual (cerca de 82% de acerto exato em conjunto independente sintético, ver `docs/deteccao.md`) não vale para dados reais. No piloto, medir com amostra aleatória dos eventos sinalizados, revisada por um humano do cliente, e registrar a taxa de falso positivo com intervalo de confiança (`docs/piloto.md`). Para recall, pedir ao cliente uma lista de casos conhecidos que deveriam ter sido pegos. Categorias com muito falso positivo ficam em sombra.

## Registro de evidências

Copiar a tabela para um arquivo por rodada (por exemplo `docs/evidencias/AAAA-MM-DD.md`). Sem dados pessoais ou segredos reais nas evidências.

| Passo | Caso | Data | Commit | Versão do terceiro | Executor | Resultado | Evidência | Desvio ou ação |
|---|---|---|---|---|---|---|---|---|
| 1 | Sessão interativa | | | | | NÃO EXECUTADO | | |
| 2 | Login com PKCE | | | | | NÃO EXECUTADO | | |
| 3 | Enter/botão/colar | | | | | NÃO EXECUTADO | | |
| 4 | Test connection | | | | | NÃO EXECUTADO | | |
| 5 | Webhook com HMAC | | | | | NÃO EXECUTADO | | |
| 6 | Saturação | | | | | NÃO EXECUTADO | | |
| 7 | Restauração | | | | | NÃO EXECUTADO | | |
