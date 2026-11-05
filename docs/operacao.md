# Operação: backup, restauração, retenção, chaves, logs e métricas (Etapa 9)

Tudo o que está aqui foi exercitado pelos testes indicados, no PostgreSQL local. O que não foi testado está marcado.

## Variáveis de ambiente da operação

| Variável | Padrão | Para quê |
|---|---|---|
| `ORIGINAL_TEXT_MASTER_KEY` | (vazia) | chave mestra de 32 bytes em base64 urlsafe. Sem ela, guardar texto original, segredos de canais e o segredo dos inference hooks **falha** com mensagem clara. Guarde-a fora do banco e fora do backup. |
| `RATE_LIMIT_KEY_PER_MINUTE` | 6000 | limite por chave de API, por processo (0 desliga). Os coletores de uma empresa inteira usam uma chave. |
| `RATE_LIMIT_USER_PER_MINUTE` | 600 | limite por usuário do console, por processo (0 desliga) |
| `METRICS_TOKEN` | (vazio) | habilita `GET /metrics` com `Authorization: Bearer <token>`. Sem token, a rota responde 404. |
| `LOG_JSON` | true | logs em uma linha JSON, sem conteúdo |
| `WORKER_INTERVAL` | 10 | segundos entre passadas do worker (entrega de notificações, relatórios agendados, retenção) |
| `OLD_MASTER_KEY` / `NEW_MASTER_KEY` | — | só para `python -m app.cli rewrap-keys` |
| `INFERENCE_HOOK_BUDGET_MS` | 3000 | orçamento de tempo do endpoint dos inference hooks |
| `INFERENCE_HOOK_MAX_BODY_BYTES` | 67108864 | corpo máximo aceito (64 MiB, o máximo do protocolo) |
| `SMTP_HOST` | (vazio) | sem ele, o envio de e-mail falha com mensagem clara |

## Backup e restauração

```bash
# backup (use a URL do DONO do banco; a do papel restrito não enxerga todas as linhas por causa da RLS)
infra/backup.sh "postgresql://dono:senha@host:5432/promptshield" /seguro/promptshield-2026-10-15.dump

# restauração SEMPRE em um banco vazio novo
createdb promptshield_restaurado
infra/restore.sh /seguro/promptshield-2026-10-15.dump "postgresql://dono:senha@host:5432/promptshield_restaurado"
```

- `restore.sh` confere a soma SHA-256, recusa banco de destino que não esteja vazio e recusa um arquivo cuja soma não bate.
- **O backup não contém a chave mestra.** Guarde-a em outro lugar, com outro controle de acesso. Sem ela, textos originais cifrados e segredos de canais do backup não podem ser lidos (isto é proposital); texto mascarado e metadados ficam legíveis. **Cifre o arquivo de backup e restrinja o acesso** (o script só usa `umask 077`).
- Teste: `apps/api/tests/test_backup_restore.py` faz o ciclo completo e prova que os dados voltam, que RLS e a imutabilidade da auditoria continuam valendo, que o papel restrito só vê o próprio tenant, que a chave mestra não está no arquivo e que o texto original abre com a chave certa e não com outra. **Não foi testado:** restauração em outra versão do PostgreSQL, bancos grandes, restauração parcial por tenant (não existe: restaura-se tudo e depois aplica-se a retenção).
- Depois de restaurar um backup antigo, **reaplique os pedidos de eliminação de titulares** recebidos depois da data do backup (o backup traz de volta dados já eliminados). Isso é um risco conhecido de qualquer backup; mantenha o registro dos pedidos fora do banco ou comece por `POST /v1/privacy/subject/erase`.

## Retenção

- `retention_days` (padrão 90, de 7 a 365) vale para eventos, análises, incidentes, alertas, fila de envio concluída, registros dos inference hooks e relatórios.
- `original_retention_days` (padrão 30, de 1 a 365, nunca maior que a retenção geral): só o texto original cifrado é apagado nesse prazo; o texto mascarado fica até o prazo geral.
- A retenção usa `received_at` (hora do servidor), não `occurred_at` (vem do coletor).
- O worker executa a retenção uma vez por dia por tenant; o administrador pode executar na hora com `POST /v1/privacy/retention/run`. Cada execução grava `retention.run` na auditoria com as contagens.
- O registro de auditoria **não** é apagado (imutável por gatilho). Ele não leva texto de prompt, mas leva justificativas digitadas pelos usuários: oriente a não colocar dado pessoal nelas.
- Teste: `apps/api/tests/test_privacy.py::test_retention_deletes_what_expired_and_only_that`.

## Chaves

| Chave | Rotação | Teste |
|---|---|---|
| Chave de API de coletor | `POST /v1/api-keys/{id}/rotate` cria a nova e deixa a antiga valer por `grace_hours` (0 revoga já); `POST /v1/api-keys/{id}/revoke`; `expires_in_days` na criação | `apps/api/tests/test_security.py` |
| Chave mestra | `OLD_MASTER_KEY=... NEW_MASTER_KEY=... python -m app.cli rewrap-keys` reembrulha as chaves de dados sem recifrar nada; depois troque `ORIGINAL_TEXT_MASTER_KEY` e reinicie | `test_master_key_rotation_rewraps_without_reencrypting` |
| Segredo de assinatura dos inference hooks | `PUT /v1/inference-hook/secret` (o anterior vale por 10 minutos) | `apps/api/tests/test_inference_hook.py` |
| Chave de dados do tenant | criada na primeira necessidade; apagar o tenant apaga a chave | `test_each_tenant_has_its_own_data_key_wrapped_by_the_master_key` |

Quem tem o banco **e** a chave mestra lê tudo: não há KMS/HSM (pendência).

## Logs e métricas

- Um log de acesso por requisição, em JSON: `request_id`, `tenant_id` (UUID), modelo da rota (por exemplo `/v1/events/{event_id}`), método, status, duração. **Nunca** corpo, query string, e-mail ou texto. O cabeçalho `X-Request-ID` é aceito se for curto e alfanumérico, senão é substituído.
- `GET /metrics` (formato de texto do Prometheus): `ps_http_requests_total{route,method,status}`, `ps_http_request_duration_seconds`, `ps_events_ingested_total{channel,decision}`, `ps_inference_hook_total{outcome}`, `ps_rate_limited_total{kind}`. Sem rótulos de tenant, usuário ou chave.
- As métricas são **em memória, por processo**: com vários processos, cada um responde as suas e zeram ao reiniciar.
- Sugestões de alerta (não implementadas aqui): taxa de 5xx, `ps_rate_limited_total` subindo, `failure_allow`/`failure_deny` nos inference hooks, fila de envio `failed` na tela de canais, ausência de `retention.run` na auditoria por mais de 2 dias.

## Limites conhecidos

Limite de requisições por processo; sem Redis; sem KMS; TLS é do proxy reverso do operador; o `docker-compose` do projeto é para desenvolvimento e **nunca foi executado**.

## Inadimplência e encerramento: suspender e reativar uma empresa (só o fornecedor)

Comandos (na VM; `docker compose exec api` roda dentro do contêiner da API):

```bash
docker compose exec api python -m app.cli tenants                                   # situação de cada empresa: ativa, vencida ou SUSPENSA, máquinas e validade
docker compose exec api python -m app.cli suspend --slug acme --reason "fatura em atraso"
docker compose exec api python -m app.cli resume  --slug acme
```

**Suspensa significa:**
- A API recusa tudo que vem dos coletores dessa empresa (403 "contrato suspenso"): eventos, configuração do hook e da extensão, inference hook. Novas matrículas de máquina também são recusadas (e o token não é gasto).
- O console continua abrindo para os usuários da empresa e **só lê**: consultar, filtrar e exportar funciona; qualquer alteração (política, token, revisão, retenção) é recusada com a mesma mensagem. O administrador vê uma faixa vermelha "Contrato suspenso" com o motivo que você escreveu.
- Relatórios agendados deixam de ser gerados e enviados. A retenção continua rodando.
- **Nada é apagado.** `resume` volta tudo ao normal na hora (a verificação é feita a cada requisição, sem cache).
- Os funcionários **não são afetados**: os sensores ficam em `fail_mode: open`, então o Claude Code, o ChatGPT etc. continuam funcionando; só o monitoramento para.
- `suspend` e `resume` entram na auditoria da empresa (ator "fornecedor"). Suspender duas vezes não muda o "desde quando".

**Avisos antes de suspender:** o console mostra uma faixa amarela quando faltam 15 dias ou menos para a validade da licença (`set-license --expires`) e vermelha quando venceu. A faixa é só informação: a suspensão nunca é automática.

**O que NÃO existe ainda:** suspensão automática por data ou por falta de pagamento (cobrança, nota fiscal e boleto estão fora do escopo), aviso por e-mail ao administrador, apagamento da empresa inteira no encerramento (hoje só existe o apagamento por pessoa), painel do fornecedor no navegador. Os prazos de aviso, exportação e apagamento precisam estar no contrato (revisão jurídica pendente). Para encerrar de vez hoje: suspender, deixar o cliente exportar no prazo combinado e depois apagar manualmente no banco.

## Licenciamento on-premise (servidor do cliente)

Só vale com `LICENSE_MODE=onprem` (padrão `off`). Variáveis: `LICENSE_SERVER_URL`, `LICENSE_PUBLIC_KEY` (do fornecedor, fixada), `LICENSE_ALLOW_HTTP` (só teste), `LICENSE_STATE_DIR` (padrão `/var/lib/promptshield`). **O volume `licensedata` guarda a chave privada da instalação: faça backup dele junto com o banco** e guarde com o mesmo cuidado do `.env`. Sem ele a instalação perde a identidade e precisa de `unbind` e um código novo do fornecedor. O worker renova a autorização sozinho; a página **Licença** mostra o estado, os prazos, o último contato e o último erro. Métricas: `ps_license_refusals_total`. Detalhes e ensaio de validação: [`licenciamento.md`](licenciamento.md).

