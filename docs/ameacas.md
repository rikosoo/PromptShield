# Modelo de ameaças do PromptShield (STRIDE), Etapa 9

Escopo: o próprio produto (API, console, extensão, hook do Claude Code, endpoint dos inference hooks, worker, banco, backups). Estado em 2026-10-15. **Nenhum teste de intrusão externo foi feito.** Cada mitigação "implementada" aponta o teste que a prova; o que não tem teste está em "Pendências".

STRIDE: **S**poofing (falsificar identidade), **T**ampering (adulterar), **R**epudiation (negar autoria), **I**nformation disclosure (vazar), **D**enial of service (negar serviço), **E**levation of privilege (ganhar poder).

## O que protegemos (ativos)

| Ativo | Por que importa |
|---|---|
| Texto dos prompts (mascarado) e metadados de uso por pessoa | dado pessoal de colaboradores; pode revelar o que a empresa faz |
| Texto original cifrado (opcional, desligado por padrão) | o dado mais sensível do produto |
| Chave mestra, chaves de dados por tenant, segredos de canais e dos inference hooks | quem as tem lê tudo |
| Chaves de API dos coletores | enviam eventos como o tenant; sem escopo de leitura |
| Registro de auditoria | prova de quem viu o quê; imutável |
| Políticas | se adulteradas, desligam a proteção do cliente |

Fronteiras de confiança: navegador do usuário e extensão (não confiáveis) → console (BFF) → API → PostgreSQL com RLS; Anthropic → endpoint dos inference hooks; API → destinos de webhook/SMTP/syslog do cliente; backup fora do servidor.

Suposições: o servidor de aplicação e o banco são administrados pelo operador do produto; quem é dono da máquina de um usuário final pode alterar a própria extensão ou hook (o produto **não** é controle contra o dono da máquina, como diz `docs/claude-code-hooks.md`).

## Resumo: o que um atacante ganha ao comprometer cada parte

| Parte comprometida | O que o atacante ganha | Principal limite |
|---|---|---|
| **API (execução de código no servidor)** | lê e altera tudo que a aplicação alcança. O papel `promptshield_app` não tem BYPASSRLS, mas a aplicação define `app.tenant_id` por conta própria: quem controla o processo escolhe o tenant. A chave mestra está no ambiente do processo e decifra os originais e segredos. | a RLS protege contra SQL injection e erro de código, **não** contra o processo comprometido. Pendência: KMS/HSM. |
| **Console (BFF)** | o token da sessão de quem estiver logado (cookie httpOnly: não vai para JavaScript do navegador); a chamada à API acontece com esse token. Não guarda segredos de tenant. | CSRF, XSS e proxy abertos tratados abaixo. |
| **Extensão de navegador** | a chave de API do tenant (guardada no service worker) e o texto que o usuário digita nos sites monitorados. A chave só envia eventos e lê a configuração; não lê nada de outros usuários nem de outros tenants. | a extensão só age nos domínios configurados (interseção, nunca ampliação). |
| **Hook do Claude Code (máquina de um usuário)** | a chave de API do tenant, legível pelos usuários da máquina (documentado). | mesmo limite da chave de coletor. |
| **Chave de API de coletor** | injetar eventos falsos no tenant (poluir métricas, abrir alertas) até o limite de requisições. **Não** lê eventos. | rotação e expiração; limite por chave. |
| **Banco (acesso direto como dono)** | lê textos mascarados, metadados e hashes de chaves; **não** lê originais nem segredos sem a chave mestra, que não está no banco nem no backup. | a DEK do tenant está no banco, embrulhada pela chave mestra. |
| **Backup roubado** | o mesmo que o banco, sem a chave mestra: textos originais e segredos de canais ficam ilegíveis. | o texto mascarado e os metadados ficam legíveis (cifrar o arquivo de backup é pendência do operador). |
| **Conta de admin do console** | tudo do tenant, inclusive pedir o texto original (com justificativa auditada) e eliminar dados. | insider: sem aprovação em dupla (pendência). |
| **Endpoint dos inference hooks** | quem tem a chave de API **e** o segredo de assinatura envia frames falsos: gera eventos, e (em modo aplicar) negaria pedidos legítimos de uma organização. | sem o segredo, nada é aceito (401). |

## STRIDE por componente

### API e banco

| | Ameaça | Mitigação implementada (teste) | Pendência |
|---|---|---|---|
| S | usar credencial inventada, expirada ou revogada | chaves guardadas só como SHA-256; expiração e revogação na função `auth_api_key`; `test_no_credentials_means_401_on_every_protected_route`, `test_rotation_keeps_old_key_for_the_grace_period_then_expires_it` | MFA e política de senha são do provedor OIDC; OIDC nunca foi testado contra um provedor real |
| S | token de login forjado | JWT verificado (assinatura, emissor, audiência, expiração, e-mail verificado); `apps/api/tests/test_oidc.py` | `OIDC_MODE=mock` não pode ir para produção: a rota `/dev/token` só existe nesse modo (`test_dev_token_route_does_not_exist_unless_mock_mode_is_on`) |
| T | ler ou gravar dados de outro tenant | RLS ENABLE+FORCE em todas as tabelas com tenant; papel da aplicação sem BYPASSRLS; `apps/api/tests/test_isolation.py`, matriz de acesso | a aplicação define o tenant (ver acima) |
| T | alterar o registro de auditoria | gatilho que recusa UPDATE e DELETE, até para o dono; teste de restauração prova que o gatilho volta com o backup | o dono do banco pode remover o gatilho (controle de operação, não de aplicação) |
| R | negar ter lido o texto original ou apagado dados | toda leitura de original, eliminação de titular, rotação de chave, mudança de política e de canal grava auditoria com o UUID do ator; `test_only_admin_and_analyst_can_ask_for_the_original_text_and_each_ask_is_audited` | auditoria não é exportada para fora do banco (pode ir ao SIEM pelo `GET /v1/audit-log`) |
| I | vazar texto de prompt em log, métrica ou erro | logs JSON só com modelo da rota, método, status, duração, UUIDs; métricas sem tenant, usuário ou conteúdo; erro interno registra só o tipo; `test_logs_never_contain_prompt_text_emails_or_secrets`, `test_metrics_are_off_without_token_and_never_carry_tenant_or_user` | proxies reversos do cliente podem registrar URLs (inclusive query com `user_id`): configurar no proxy |
| I | ler o texto original sem papel | só admin e analista, com justificativa de 10+ caracteres e auditoria; nenhuma rota de leitura devolve original; matriz de acesso (`test_role_matrix_every_route_every_role`) | |
| I | segredo de canal ou de hook em claro | cifrados com chave derivada da DEK do tenant; a URL de webhook também (`test_channel_url_is_encrypted_at_rest`, `test_secret_never_leaves_the_api_and_is_encrypted_at_rest`) | |
| I | injeção SQL | SQLAlchemy com parâmetros; as poucas consultas em texto usam parâmetros ou fragmentos constantes; análise estática (regras S do ruff) no CI | |
| D | inundar a API | limite por chave (padrão 6.000/min) e por usuário (600/min), 429 com `Retry-After`; `test_rate_limit_per_api_key_returns_429_with_retry_after` | o limite é **por processo, em memória**; não há limite para requisições **sem** credencial (consomem uma consulta à função de autenticação); corpo de até 64 MiB nos inference hooks fica em memória: limitar no proxy |
| E | usuário comum chamar rota de admin | matriz: cada rota × cada papel; rota nova sem expectativa **reprova o teste** | |
| E | SSRF pelos canais de webhook | só https, IP público, conexão no IP validado, sem redirecionamento (`apps/api/tests/test_stage7.py`) | a checagem no momento do uso reduz, mas não elimina, uma janela de troca de DNS entre validação e conexão em syslog |

### Console web (BFF)

| | Ameaça | Mitigação (teste) | Pendência |
|---|---|---|---|
| S/T | CSRF | cookie `httpOnly` + `SameSite=Lax`; mutações exigem `X-Requested-With` e `Origin` igual ao host (`lib/proxy.test.ts`) | |
| I | roubo de token por XSS | token só em cookie httpOnly, nunca em JavaScript; CSP restritiva (sem domínios externos, `frame-ancestors 'none'`); teste no navegador confere cabeçalhos e ausência de violações | `script-src` precisa de `'unsafe-inline'` por causa do Next.js: um XSS que injete script em linha **não** seria barrado pela CSP; nonces são pendência |
| I | proxy aberto para a API | o proxy só repassa `/v1/...` (`safeApiPath`) | |
| T | clickjacking | `X-Frame-Options: DENY` e `frame-ancestors 'none'` | |
| D | — | — | sem limite de requisições no próprio BFF (o da API vale por trás dele) |

### Extensão (Chrome/Edge)

| | Ameaça | Mitigação | Pendência |
|---|---|---|---|
| I | extensão captura mais do que deve | só domínios configurados pelo administrador; lista da API só restringe; aviso ao usuário; sem `host_permissions` amplas | **EXPERIMENTAL**: nunca testada nos sites reais |
| S | página hospedeira falsifica o diálogo | shadow DOM fechado em produção | |
| I | chave de API exposta | guardada no service worker, nunca no content script | rotação manual (a API suporta rotação com convivência) |

### Hook do Claude Code e inference hooks

| | Ameaça | Mitigação (teste) | Pendência |
|---|---|---|---|
| S | requisição falsa dizendo ser da Anthropic | chave de API + assinatura Standard Webhooks (HMAC-SHA256, tolerância de 5 minutos, comparação em tempo constante); sem assinatura, 401 sempre (`test_unsigned_wrong_signature_stale_timestamp_and_wrong_key_are_rejected`) | o formato é beta e nunca foi chamado por um tenant Enterprise real |
| T | repetição (replay) | tolerância de 5 minutos; `webhook-id` idempotente (eventos com id determinístico) | dentro dos 5 minutos um replay devolve o mesmo veredito (sem efeito colateral) |
| D | derrubar a organização do cliente: falha nossa com "Block the request" bloqueia todo mundo | orçamento de 3 s abaixo do limite de 5 s; falha segue `failure_mode` do tenant; sombra por padrão | decisão do cliente; documentada |
| D | corpo enorme | limite configurável (`INFERENCE_HOOK_MAX_BODY_BYTES`, 64 MiB), 413 | memória por requisição |

### Worker

| | Ameaça | Mitigação | Pendência |
|---|---|---|---|
| E | worker enxerga todos os tenants | usa o papel restrito; só `list_tenant_ids()` cruza tenants (devolve ids); o resto roda com `app.tenant_id` por tenant | um bug no worker pode misturar tenants; coberto por testes de entrega e de retenção por tenant |
| I | notificação carrega conteúdo | só metadados; nunca o texto do prompt, nem mascarado (`test_alert_is_created_deduplicated_and_notified_once_with_valid_signature`) | |

### Backup, chaves e operação

| | Ameaça | Mitigação (teste) | Pendência |
|---|---|---|---|
| I | backup vaza originais | a chave mestra não vai no backup; sem ela os textos cifrados não abrem (`test_backup_and_restore_round_trip`) | cifrar o arquivo de backup e guardar a chave mestra separadamente é do operador (`docs/operacao.md`) |
| T | backup adulterado | `restore.sh` confere a soma SHA-256 e recusa banco de destino não vazio (testado) | a soma fica ao lado do arquivo: assinar o backup é pendência |
| I | chave mestra comprometida | rotação reembrulhando as DEKs sem recifrar dados (`test_master_key_rotation_rewraps_without_reencrypting`) | **KMS/HSM não existe**; quem tem o banco e a chave mestra lê tudo |
| T/I | dependência vulnerável | `pip-audit` e `npm audit` no CI; chaves em lockfiles | sem SBOM nem assinatura de artefatos; avisos novos só aparecem quando o CI roda |

## Pendências (resumo, em ordem de risco)

1. Chave mestra em variável de ambiente (sem KMS/HSM).
2. Administrador comprometido ou mal-intencionado pode pedir originais e eliminar dados: falta aprovação em dupla e exportação contínua da auditoria.
3. CSP com `'unsafe-inline'` em scripts.
4. Limite de requisições por processo e sem limite para chamadas sem credencial; corpo de 64 MiB em memória.
5. OIDC nunca testado contra um provedor real; extensão nunca testada nos sites reais; inference hooks nunca chamados por um tenant Enterprise.
6. Backup sem cifra própria e sem assinatura; TLS fica por conta do proxy reverso do operador.
7. Sem teste de intrusão externo, SBOM ou assinatura de artefatos.
8. O registro de auditoria não tem prazo de apagamento automático (decisão em `docs/lgpd.md`).
