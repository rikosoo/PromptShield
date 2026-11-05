# Alertas, notificações e exportação para SIEM (Etapa 7)

Estado de cada integração (princípio 1). "Testado" significa testado neste repositório, contra servidores locais de teste.

| Canal | Classe | O que foi testado | O que NÃO foi testado |
|---|---|---|---|
| Webhook genérico (JSON assinado, HMAC-SHA256) | REAL | recebimento, assinatura conferida, nova tentativa, deduplicação | receptor de cliente real |
| Webhook de eventos para SIEM (mesmo formato assinado, um POST por evento) | REAL | idem | idem |
| Slack (webhook de entrada) | PARCIAL | corpo `{"text": ...}`, conforme a documentação do Slack (lida em 2026-10-14 por busca; a página não abriu neste ambiente) | um Slack de verdade |
| Microsoft Teams | EXPERIMENTAL, **A VERIFICAR** | só que o código envia o corpo descrito abaixo | tudo. As conexões do Office 365 foram aposentadas (Message Center MC1181996, desativação de 18 a 22/05/2026); o webhook do Workflows deve receber um cartão adaptável em `attachments`, mas o formato exato **não pôde ser conferido** na documentação da Microsoft |
| E-mail (SMTP) | PARCIAL | envio contra um servidor SMTP de teste local, sem STARTTLS; falha clara sem `SMTP_HOST` | STARTTLS, autenticação, provedores reais |
| Syslog com CEF | PARCIAL | UDP contra um receptor local, campos do CEF | TCP, TLS, e o receptor real do cliente (o enquadramento de TCP, uma mensagem por linha, é **A VERIFICAR**) |

## Alertas

Avaliados na ingestão de cada evento, no mesmo banco, e gravam `alerts` com uma chave de deduplicação. A chave repetida só incrementa `count`; a notificação sai **uma vez**, quando o alerta nasce.

| Regra | Dispara quando | Gravidade | Chave de deduplicação |
|---|---|---|---|
| `severidade` | o evento abre incidente `alto` ou `critico` (score ≥ 60) | a do incidente | regra, usuário, categoria principal, dia (UTC) |
| `injection` | injection direta, indireta ou jailbreak com confiança ≥ 0,8 | alto | regra, usuário, categoria, dia |
| `volume` | mais eventos por hora do que `volume_threshold_per_hour` do tenant (padrão 60; 0 desliga) | médio | regra, usuário, hora |
| `agente` | ação de agente com score ≥ 35 em categoria de agente que o usuário **não tinha** nos 14 dias anteriores, e só se ele já tem 20 ou mais eventos nesse período (sem histórico, "fora do padrão" não quer dizer nada) | alto | regra, usuário, categoria, semana ISO |

"Fora do padrão" é uma heurística simples (categoria nova para o usuário), não um modelo estatístico.

Cada canal de alerta tem `min_severity` (padrão `medio`). Cada canal de eventos (SIEM) tem `min_score` (padrão 35). A fila (`notification_outbox`) tem chave única por canal e alvo: o mesmo alerta não entra duas vezes. Falhas são retentadas com espera de 30 s, 60 s, 120 s... até `OUTBOX_MAX_ATTEMPTS` (5), depois ficam `failed` (visível na tela de canais). O worker (`python -m app.worker`) entrega a fila e gera relatórios agendados.

## Segurança dos canais

- URLs precisam ser **https** e resolver só para endereços públicos (proteção contra SSRF). A conexão é feita no IP já validado e redirecionamentos não são seguidos. As válvulas `ALLOW_INSECURE_WEBHOOKS` e `ALLOW_PRIVATE_WEBHOOK_TARGETS` existem só para desenvolvimento e testes.
- A URL de um webhook do Slack ou Teams é um segredo: a API e o console mostram só o host, e os erros nunca incluem a URL.
- O segredo HMAC é guardado cifrado (chave derivada da chave mestra, separada da usada para texto original).
- As mensagens **nunca** levam o texto do prompt, nem mascarado: só usuário, departamento, categorias, score e motivos.
- Só o administrador configura canais; cada ação grava auditoria.

## Webhook genérico (formato `promptshield.alert.v1`)

`POST` com `Content-Type: application/json`, cabeçalhos `X-PromptShield-Timestamp` (segundos) e `X-PromptShield-Signature: sha256=<hex>`, onde o hex é o HMAC-SHA256 de `timestamp + "." + corpo` com o segredo do canal. O receptor deve recusar timestamps antigos. O corpo é `{"schema": "promptshield.alert.v1", "alert": {id, tenant, rule, severity, title, user_id, department, count, first_seen, last_seen, score, categories, incident_id, console_link, note}}`. Eventos de SIEM usam `promptshield.event.v1` com `event`.

## CEF

`CEF:0|PromptShield|PromptShield|<versão da API>|<categoria principal>|<nome da categoria>|<0-10>|<extensão>`. Severidade CEF = score/10 arredondado. Escapes: no cabeçalho `\` e `|`; na extensão `\` e `=`, e quebra de linha vira `\n`. Fonte: guias de fornecedores que citam o "ArcSight CEF Implementation Standard"; **o PDF oficial não pôde ser aberto neste ambiente**, então confirme o escape de quebra de linha com o seu SIEM.

| Chave CEF | Conteúdo |
|---|---|
| `rt` | quando o evento ocorreu (milissegundos desde 1970) |
| `externalId` | `event_id` |
| `suser` | usuário |
| `act` | decisão aplicada (`allow`, `mask`, `block`...) |
| `cat` | categoria principal |
| `cn1` / `cn1Label=riskScore` | score 0 a 100 |
| `cs1` / `categories` | todas as categorias |
| `cs2` / `app` | ferramenta |
| `cs3` / `department` | departamento |
| `cs4` / `policyWouldDecide` | decisão que a política teria tomado (em modo monitorar, difere de `act`) |
| `cs5` / `scoreVersion` | versão da fórmula de score |
| `cs6` / `channel` | canal de captura |
| `msg` | motivos do score, ex.: `Regra (+60); outra (+10)` |

Syslog: envelope RFC 5424 (`<14>1 <timestamp> promptshield promptshield - - - CEF:0|...`). A RFC 5424 não pôde ser aberta aqui; o formato do envelope segue o conhecimento do autor e deve ser conferido com o coletor do cliente.

Por consulta (sem canal): `GET /v1/export/cef` e `GET /v1/export/events.jsonl` (parâmetros `since`, `min_score`, `limit`), papéis auditor e administrador, com auditoria.

## Score por usuário e departamento

Indicador para priorizar revisão humana, nunca prova de má conduta (a tela e os relatórios dizem isso). Fórmula versionada em `apps/api/app/risk.py`:

`score do usuário = min(100, maior score de evento no período + min(20, 5 × (eventos com score ≥ 35 − 1)))`

O departamento é a média dos scores dos usuários com atividade. A série de evolução aplica a mesma fórmula dia a dia. O score do evento (motor de detecção) é puro e não depende de histórico; **a repetição entra só na agregação por usuário**, para o mesmo evento dar sempre o mesmo score e os mesmos motivos.

## Relatórios

`POST /v1/reports` gera na hora e guarda uma cópia (PDF ou CSV; hash SHA-256 na listagem); `POST /v1/reports/schedules` agenda (mensal: mês civil anterior; semanal: semana ISO anterior), executado pelo worker uma única vez por período. Os totais vêm da mesma função do painel (`compute_overview`) e o teste confere os números do PDF e do CSV contra `/v1/stats/overview`. Executivo: resumo, comparação com o período anterior, departamentos, categorias, incidentes, alertas e ranking de indicador de risco. LGPD: eventos com dado pessoal (pii, saúde, financeiro, RH, cliente) por tipo de dado, categoria, ferramenta e departamento, contas pessoais, ações tomadas e acessos auditados ao texto original; **o modelo precisa de revisão jurídica**. O CSV neutraliza fórmulas de planilha (`=`, `+`, `-`, `@`). Geração e e-mail dependem de `SMTP_HOST` para o envio; sem ele o relatório é gerado e guardado e o erro de envio fica na auditoria.
