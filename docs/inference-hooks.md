# Inference hooks do Claude Enterprise: o que a documentação confirma e como o PromptShield os usa (Etapa 8)

Lido em **2026-10-15** nas páginas oficiais, por inteiro:
- [Visão geral](https://platform.claude.com/docs/en/manage-claude/inference-hooks)
- [Configurar](https://platform.claude.com/docs/en/manage-claude/inference-hooks-configuration)
- [Desenvolver uma integração (endpoint)](https://platform.claude.com/docs/en/manage-claude/inference-hooks-endpoint)

**Beta.** A documentação diz: "Field names, request shapes, and headers may change during the beta." Disponível só para organizações **Claude Enterprise**. Tudo abaixo é do que está nessas páginas; o que não está marcado como confirmado é **A VERIFICAR**.

## Estado da nossa integração

**PARCIAL.** O protocolo é documentado em detalhe e o nosso endpoint o implementa e é testado com requisições simuladas conforme os exemplos da documentação (assinatura, prompt, tool call, veredito, tempo). **Nunca foi chamado por um tenant Claude Enterprise de verdade.** Por isso os eventos gravam `integration_status = partial` (e não `real`), apesar de o protocolo ser documentado. Depende do plano Enterprise e de uma funcionalidade em beta, cujo suporte pela Anthropic também é beta.

## Como o hook é chamado

1. O usuário envia um prompt em uma superfície governada (claude.ai, Cowork, Claude Code, Claude Tag; web, desktop, mobile, CLI, Slack).
2. A Anthropic envia um `POST` HTTPS ao endpoint configurado, com a transcrição, e **espera** o veredito. Um pedido negado nunca chega ao modelo.
3. Nosso servidor responde `allow` ou `deny` dentro do tempo limite (padrão 5.000 ms; configurável de 1 a 10.000 ms).
4. `allow`: segue. `deny`: o usuário vê `deny_reason` (até 500 caracteres) seguido do texto fixo que o administrador configurou. A negação vai para o Activity Feed.

Dois eventos:
- `prompt`: uma vez por pedido de inferência governado, antes de a inferência começar.
- `tool_call`: quando a resposta do Claude contém chamadas de ferramenta, antes de qualquer uma rodar, **só se** o administrador ligou "Validate tool calls" (vem ligado por padrão numa configuração nova). Um veredito cobre **todas** as chamadas do frame (não dá para permitir umas e negar outras). Negar encerra a resposta; texto já entregue antes da primeira chamada não é retirado.

## Requisitos do endpoint (documentados)

- URL `https://` na **porta 443**, host **publicamente roteável com IPv4**, certificado válido na cadeia pública, **sem redirecionamento**. `localhost`, IPv6, endereços privados, loopback e CGNAT são recusados. Túneis reversos (ngrok e similares) não funcionam.
- A URL inteira é o endpoint: não há sufixo fixo.
- Origem das requisições: `160.79.106.0/24` (faixas de saída da Anthropic). Liberar esse bloco reduz exposição, **não substitui** a verificação de assinatura.
- Cabeçalhos fixos: `Content-Type: application/json`, `User-Agent: anthropic-dlp/1`, `Accept-Encoding: identity` (a resposta não pode ser comprimida). Mais até 16 cabeçalhos estáticos que o administrador define (valores guardados cifrados pela Anthropic; usamos `X-API-Key` para identificar o tenant).

## Autenticação e verificação

Padrão [Standard Webhooks](https://www.standardwebhooks.com/): `webhook-id` (igual ao `request_id` do corpo; chave de idempotência), `webhook-timestamp` (segundos; rejeitar mais de 5 minutos de diferença nos dois sentidos) e `webhook-signature` (um ou mais `v1,<base64>`, separados por espaço; cada um é HMAC-SHA256 de `{webhook-id}.{webhook-timestamp}.{corpo em bytes}`; comparação em tempo constante).

Detalhes que a documentação destaca como fonte de erro: verificar sobre os **bytes crus** do corpo; decodificar o segredo (valor depois de `whsec_`) com base64 **padrão** (`+` e `/`), não URL-safe.

**Rotação do segredo é troca imediata**, sem sobreposição: requisições assinadas com o segredo antigo ainda podem chegar por cerca de um minuto, mais o que estava em voo. O servidor deve aceitar os dois durante a troca. O primeiro segredo é gerado no primeiro salvamento e mostrado **uma vez**.

Organizações que ligaram o hook antes de o segredo ser obrigatório enviam requisições sem assinatura até o administrador gerar um. **O PromptShield recusa requisições sem assinatura sempre** (401): é mais seguro; o custo é que esse caso raro exige gerar o segredo antes de ligar.

## O que é enviado (corpo)

Campos do frame `prompt`: `type`, `request_id`, `tenant_id` (identificador opaco **da organização na Anthropic**, não o nosso), `actor` (`type: "user"`, `id`, `email_address`; ambos podem ser nulos), `source.application` (string aberta; comuns: `claude-ai`, `claude-code`, `cowork`; `config-test` nos testes de conexão e nas verificações de recuperação), `messages`, `session_id` (opaco; no Claude Code é "best-effort, client-asserted"), `model`, `metadata` (reservado, vazio hoje).

`messages`: papéis `user` e `assistant` (resultados de ferramenta vêm como `user`). Blocos: `text`; `tool_use` (`id`, `tool_name`, `input`, e `tool_info` só no frame `tool_call`); `tool_result` (`content` em texto, `is_error`, `tool_name`, `tool_use_id`); `attachment` (`file_name`, `media_type`, `size_bytes`, `text`, que pode ser nulo). Turnos cujos blocos foram todos excluídos são omitidos: não assuma alternância.

O frame `tool_call` traz `messages` com **só** a última mensagem do `assistant` (leia a última entrada do array). `tool_info` é `platform`, `application`, `third_party` (com `origin` e `verified_origin`) ou `client`.

**A transcrição inteira é reenviada a cada turno**, sem truncar. O corpo costuma ficar abaixo de ~10 MB, mas o protocolo permite até **64 MiB**. Um corpo rejeitado pelo servidor (por exemplo, limite de 1 MB do nginx) é falha do webhook e, com "Allow the request", o prompt chega ao modelo **sem inspeção**.

## O que NUNCA é enviado

System prompts, definições de ferramentas, contexto interno da Anthropic, raciocínio oculto do Claude, **bytes crus de arquivos e imagens** (conteúdo só em imagem, como a captura de tela de um documento, **não é inspecionado**). Conversas de voz: prompts e tool calls são enviados, mas uma pequena parcela das chamadas não é; não use como único controle. Com "Validate tool calls", chamadas a algumas ferramentas do próprio claude.ai (listar/sugerir conectores, hora local, memória, etc.) podem não gerar frame; aparecem no próximo `prompt`.

## Resposta (veredito)

HTTP **200** e JSON, para os dois resultados:

```json
{"action": "allow"}
{"action": "deny", "deny_reason": "texto para o usuário (até 500 caracteres)", "reference_id": "até 50 caracteres [A-Za-z0-9._:/-]"}
```

`reference_id` fica na atividade `inference_hooks_request_denied` do Activity Feed e **nunca** é mostrado ao usuário: serve para juntar a negação ao nosso registro. Campos desconhecidos são ignorados; `deny_reason` longo é truncado; `reference_id` malformado é descartado em silêncio; o `action` sempre vale. **Qualquer coisa diferente de HTTP 200 com veredito válido é falha do webhook, nunca uma negação.** `action` diferente de `allow`/`deny` também é falha. Limite de 64 KiB na resposta, sem compressão, sem redirecionamento.

## Tempo limite, nova tentativa e falhas

- O tempo limite cobre a troca inteira (conexão, TLS, requisição, resposta); mesmo valor para `tool_call`.
- Nova tentativa: **exatamente uma**, após 100 ms, **somente** se a conexão falhar; usa o mesmo `webhook-id` e a mesma assinatura. Depois que respondemos, nunca há nova tentativa.
- Falhas (tempo, não-200, corpo ilegível ou grande demais, endpoint inalcançável) **nunca** viram negação: a configuração de falha do administrador decide: "Block the request" (fecha) ou "Allow the request" (abre, **padrão** na primeira configuração).
- **Disjuntor:** falhas sustentadas do nosso lado (tempo, não-200, corpo inválido, endereço proibido) o abrem e a Anthropic para de nos chamar, aplicando a configuração de falha a **todos** os pedidos; com "Block", todos os usuários da organização ficam bloqueados até resetar. Reset automático: 10 minutos depois, uma requisição de teste (`config-test`, assinada, sem conteúdo) no máximo a cada minuto; um veredito válido (allow ou deny) fecha o disjuntor. Qualquer mudança de configuração interrompe a recuperação automática. Prompt e tool call compartilham o mesmo disjuntor. Em modo sombra nenhum erro conta para o disjuntor.

## Implantação gradual (lado da Anthropic)

Três estados: desligado; **sombra** (recebemos prompts e devolvemos vereditos, nada é bloqueado, nem se negarmos nem se falharmos); aplicando. Também: porcentagem de requisições inspecionadas (sorteio por turno de conversa), exclusão de papéis personalizados, mensagem fixa de bloqueio (até 500 caracteres) e "Validate tool calls". Configurar exige a permissão `organization:manage`, que só **Owner** e **Primary owner** têm (o papel Admin não tem). A negação fica na conversa do claude.ai ("a message that a hook blocks on claude.ai stays in the conversation"). Continuar uma conversa depois de um bloqueio exige editar a mensagem negada (a transcrição inteira vai de novo).

## O que ainda não é coberto

- **A resposta do modelo não passa pelo hook** (só prompt e chamada de ferramenta; resultado de ferramenta aparece no próximo `prompt`). Para respostas, só depois, via Compliance API (fora do escopo desta etapa).
- Organizações **Platform** (API direta), **Amazon Bedrock** e **Google Cloud**: fora do escopo do hook.
- **Não há reescrita nem mascaramento**: só `allow` ou `deny`. Por isso `mask` e `ask_justification` do nosso motor viram `deny` com mensagem pedindo para remover o dado.
- Chamadas que a Anthropic faz por conta própria (títulos de conversa, Claude Security, Code Review, smart reports) não são governadas.
- Contas pessoais fora da organização Enterprise não passam pelo hook.
- Não há como saber, pela documentação, se campos novos aparecem ou mudam de nome durante o beta: **A VERIFICAR** a cada versão.

## Como o PromptShield implementa

Biblioteca pura `packages/adapters/inference_hooks` (verifica assinatura, converte transcrição em eventos universais, monta o veredito) e a rota `POST /v1/inference-hook` na API. Decisões, com o motivo:

| Tema | Escolha |
|---|---|
| Identificar o tenant | Cabeçalho estático `X-API-Key` (chave com escopo `ingest`, a mesma dos outros coletores; revogável) configurado pelo administrador do Claude. O `tenant_id` do corpo é da Anthropic e não é usado para isso. |
| Assinatura | Segredo `whsec_...` colado no console (`PUT /v1/inference-hook/secret`), guardado cifrado. A troca mantém o segredo anterior aceito por 10 minutos. Requisição sem assinatura ou com assinatura inválida: 401. |
| Modo | **Sombra por padrão** (princípio 7): sempre devolve `allow`, grava a decisão que teria tomado. `enforce` é opção explícita e exige segredo configurado. Além disso, cada política tem o próprio modo (monitorar ou aplicar): só decisões de políticas em **aplicar** viram `deny`. |
| O que é analisado | Escopo `full` (padrão): todos os blocos da transcrição, mas cada bloco só é analisado **uma vez** (identificado por hash do conteúdo, usuário e sessão); blocos já vistos reaproveitam a decisão gravada. Assim uma negação continua valendo enquanto a mensagem negada estiver na transcrição (como a documentação descreve), em vez de passar no turno seguinte. Escopo `latest`: só a última mensagem (mais barato, mas conteúdo negado chega ao modelo no turno seguinte). |
| Mapeamento | `prompt`: texto do usuário. `response`: texto de turnos anteriores do assistente. `tool_call`: `tool_use`. `tool_result`: resultado de ferramenta (injection indireta). `file_upload`: anexo com texto extraído. Anexos sem texto não são inspecionados. |
| `deny_reason` | Montado só com nomes de categorias (nunca o conteúdo), por exemplo "contém segredo ou chave". Inclui o link da política de uso do tenant, se houver. |
| Falha própria | Erro interno ou estouro do orçamento de tempo (`INFERENCE_HOOK_BUDGET_MS`, padrão 3.000 ms, abaixo dos 5.000 ms padrão da Anthropic): segue o `failure_mode` do tenant (`open` permite; `closed` nega); em sombra sempre permite. O orçamento é conferido a cada bloco. |
| Idempotência | Cada bloco gera um evento com id determinístico; repetir o mesmo `webhook-id` devolve o mesmo veredito sem duplicar nada. Cada requisição gravada em `inference_hook_requests` (sem conteúdo): veredito, `reference_id`, latência, contagens. |
| `config-test` | Responde `allow` sem gravar evento (registra só o horário do último teste, visível no console). |
| Tipo desconhecido | Responde `allow` (a documentação pede isso para não gerar falha do webhook). |
| Dados | Textos já mascarados pelo motor; o corpo original não é guardado. Estado de integração dos eventos: `partial`. |

Limites do nosso lado: corpo máximo de 64 MiB (acima, 413, que a Anthropic trata como falha); a verificação de assinatura usa o corpo inteiro em memória; **TLS e a porta 443 não vêm no `docker-compose`** (é preciso um proxy reverso com certificado público na frente da API).

## Latência medida

Medida em 2026-10-15 com `apps/api/scripts/bench_inference_hook.py` (PostgreSQL 16 e API na mesma máquina de desenvolvimento, um único processo uvicorn, uma conexão HTTP por conversa; modo `aplicar`, políticas em `aplicar`; conversas sintéticas de 8 turnos com mensagens de ~700 caracteres, transcrição inteira reenviada a cada turno, um frame `prompt` e um `tool_call` por turno; 6 das 30 conversas contêm uma chave sintética no último turno e foram negadas, como esperado):

| Cenário | Requisições | p50 | p95 | p99 | máx. |
|---|---|---|---|---|---|
| 1 conversa por vez | 480 | 20,9 ms | **27,1 ms** | 33,7 ms | 151 ms |
| 4 conversas em paralelo | 480 | 78,0 ms | **125,5 ms** | 158 ms | 321 ms |

Leitura honesta:
- **Isto mede só o nosso servidor.** Não inclui a rede entre a Anthropic e o nosso endpoint, nem o TLS, nem um proxy reverso. O tempo limite da Anthropic cobre a troca inteira (padrão 5.000 ms), por isso o nosso orçamento interno é 3.000 ms (`INFERENCE_HOOK_BUDGET_MS`).
- **A vazão não cresceu com o paralelismo** (480 requisições em ~10 s nos dois casos, cerca de 48 por segundo): o processo é limitado por CPU (análise em Python). Quem tiver mais tráfego precisa de mais processos/instâncias da API; **não medimos** esse cenário.
- O custo cresce com o que é **novo** na conversa, não com o tamanho da transcrição: blocos já vistos só entram numa consulta ao banco (verificado no teste `test_repeated_transcript_blocks_are_analyzed_once`). O primeiro frame de uma conversa longa que nunca foi vista (por exemplo, depois de uma implantação parcial) analisa todos os blocos de uma vez e é o caso mais lento; se estourar o orçamento, vale o modo de falha configurado.
- Transcrições de vários MB, anexos grandes e o NER opcional (Presidio) **não foram medidos**.
- Nenhum teste de carga de longa duração foi feito.

Como reproduzir: `DATABASE_URL_TEST=... python apps/api/scripts/bench_inference_hook.py --conversations 30 --turns 8 --workers 1` (apaga o banco indicado).
