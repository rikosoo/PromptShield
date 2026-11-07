# Arquitetura

```
coletor -> evento universal -> motor de detecção -> política -> console
```

| Parte | Pasta | Estado |
|---|---|---|
| API (FastAPI) | `apps/api` | ingestão, políticas, incidentes, auditoria; RLS por tenant (Etapa 3) |
| Console (Next.js) | `apps/web` | console (Etapa 6): BFF com cookie httpOnly e proxy `/api/proxy/v1/*` para a API |
| Motor de detecção | `packages/detection` | motor de detecção (ver `docs/deteccao.md`) |
| Taxonomia | `packages/taxonomy` | `taxonomy.yaml` com 30 categorias |
| Adaptador Claude Code | `packages/adapters/claude_code_hook` | hook de comando (Etapa 4) |
| Adaptadores restantes | `packages/adapters` | inference hooks (Etapa 8) |
| Extensão | `apps/extension` | Chrome/Edge MV3 para ChatGPT web e Claude.ai (Etapa 5, EXPERIMENTAL) |

Banco: PostgreSQL 16. Row-level security entra na Etapa 3, junto com as tabelas de eventos.

Matriz de viabilidade das integrações: `docs/viabilidade.md`.

## Console (Etapa 6)

```
navegador --cookie httpOnly--> Next.js (BFF) --Bearer--> API --RLS--> PostgreSQL
```

O token nunca chega ao JavaScript do navegador. O proxy só aceita `/v1/...` e exige cabeçalho `X-Requested-With` e `Origin` igual ao `Host` nas mutações. Login: `mock` (desenvolvimento) ou OIDC Authorization Code + PKCE (não testado contra provedor real). Todas as telas usam a mesma janela de tempo (`window_start`: 00:00 UTC do primeiro de N dias) para que os números de visão geral, lista e categorias batam.

## Alertas, SIEM e relatórios (Etapa 7)

```
ingestão -> análise -> incidente/alerta (deduplicado) -> fila de envio (outbox) -> worker -> webhook | Slack | Teams | e-mail | syslog/CEF
                                                                              \-> relatórios agendados (PDF/CSV)
```

Tudo roda sobre o mesmo PostgreSQL com RLS. O worker (`python -m app.worker`) usa o papel restrito; só `list_tenant_ids()` (função SECURITY DEFINER que devolve ids) cruza tenants. Detalhes, estado de cada integração e mapeamento de campos: `docs/siem.md`.

## Inference hooks do Claude Enterprise (Etapa 8)

```
Anthropic --POST assinado (frame prompt | tool_call)--> /v1/inference-hook --verifica assinatura--> blocos --> motor --> política
                                                                                     \-> veredito {allow|deny} (HTTP 200)
```

`packages/adapters/inference_hooks` (biblioteca pura: assinatura Standard Webhooks, frames, veredito) e `apps/api/app/inference_hook.py` (escopo, deduplicação por bloco, modo sombra, modo de falha, registro sem conteúdo em `inference_hook_requests`). Protocolo, limites e medição de latência: `docs/inference-hooks.md`. Estado: PARCIAL (nunca chamado por um tenant Enterprise real).

## Privacidade, segurança e operação (Etapa 9)

```
chave mestra (ambiente, fora do banco e do backup) --embrulha--> chave de dados do tenant (tabela tenant_keys) --deriva--> texto original, segredos de canais
worker (diário): retenção por tenant (original 30 d, resto 90 d)   |   API: direitos do titular, mapa de dados, limite por credencial, rotação de chaves
logs JSON e /metrics sem conteúdo   |   infra/backup.sh + restore.sh   |   piloto: cobertura, falso positivo por amostragem, tempo até o primeiro alerta
```

Modelo de ameaças (STRIDE): `docs/ameacas.md`. Mapa de dados, bases legais sugeridas (LGPD, GDPR, EUA) e modelos de aviso e política: `docs/lgpd.md`. Operação: `docs/operacao.md`. Piloto: `docs/piloto.md`.

## Todos os prompts (histórico pesquisável)

Página `/history` do console. Usa `GET /v1/events` (filtros: `user_q`, `q`, `app`, `kind`, `category`, `decision`, `department`, `date_from`/`date_to`/`days`, `personal_account`, `session_id`; total no cabeçalho `X-Total-Count`), `GET /v1/people` (volume, risco e última atividade por pessoa) e `GET /v1/events/export.csv` (admin e auditor; auditado). A busca atua só no texto já mascarado, nunca no original.

## Licenciamento on-premise

Serviço separado do fornecedor (`apps/licensing`, banco próprio, tabelas `lic_*`) + biblioteca pura (`packages/licensing`) + cliente dentro da API (`app/license_client.py`, tabela `license_state`, rotas `/v1/license/*`, renovação no worker). O estado da licença é uma função pura sobre a autorização assinada guardada; a API aplica o resultado em um único ponto (`security.current_principal` para inspeção e escrita, `license.check_new_seat` para matrícula). Ver [`licenciamento.md`](licenciamento.md).


## Grupos, exceções e domínios permitidos

```
administrador --> /v1/groups | /v1/policies/{id}/exceptions | /v1/allowlist | /v1/keywords --> tabelas com RLS (migrações 0019 e 0021) + auditoria
ingestão: grupos do usuário + exceções vigentes + domínios --> analyze(allowed_hosts) e policy_engine.evaluate --> decisão
```

`app/governance.py` lê o contexto na sessão do tenant; a regra de exceção é função pura em `policy_engine`. Exceção por grupo vale só para **membros cadastrados no servidor**, nunca para o grupo que o sensor declara no evento. A lista de domínios alimenta `allowed_hosts` do motor (rede externa, instalação de pacote, envio de dados). Só `host` existe hoje.
