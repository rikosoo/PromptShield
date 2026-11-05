# Inference hooks do Claude Enterprise (beta)

Biblioteca pura (só a biblioteca padrão do Python) com as três peças do protocolo, mais a rota `POST /v1/inference-hook` na API (`apps/api`). Leia primeiro [`docs/inference-hooks.md`](../../../docs/inference-hooks.md): o que a documentação oficial confirma, o que não é coberto e a latência medida.

**Honestidade sobre o estado:** isto depende do plano **Claude Enterprise** e de uma funcionalidade em **beta** da Anthropic (o suporte também é beta; campos, formatos e cabeçalhos podem mudar). Foi testado com requisições simuladas conforme os exemplos da documentação. **Nunca foi chamado por um tenant Enterprise real.** Classe: **PARCIAL**.

| Módulo | Faz |
|---|---|
| `signature.py` | verifica `webhook-id`/`webhook-timestamp`/`webhook-signature` (Standard Webhooks; tolerância de 5 minutos; base64 padrão; vários segredos para a troca) |
| `frames.py` | converte o corpo (`prompt` ou `tool_call`) em blocos para o evento universal; ignora o desconhecido |
| `verdict.py` | monta `{"action": "allow"}` ou `deny` com `deny_reason` (≤ 500) e `reference_id` (≤ 50) |

## Como o administrador do cliente configura

Pré-requisitos no cliente: plano **Claude Enterprise** e alguém com o papel **Owner** ou **Primary owner** (Admin não basta).

1. **Publique a API do PromptShield** em `https://…` na **porta 443**, host público com IPv4, certificado válido na cadeia pública e **sem redirecionamento**. O `docker-compose` do projeto **não** traz TLS: ponha um proxy reverso na frente. Túneis (ngrok etc.) não funcionam. O corpo pode ter até 64 MiB: ajuste o limite do proxy (o padrão de 1 MB do nginx faria o prompt passar **sem inspeção** se o Claude estiver em "Allow the request").
2. No claude.ai: **Organization settings > Data and privacy > Inference hooks > Allow for your organization**.
3. **Configure**: URL `https://SUA-API/v1/inference-hook`. O segredo `whsec_…` aparece **uma vez**: no console do PromptShield (**Inference hooks**) cole em "Segredo de assinatura".
4. **Custom request headers**: `X-API-Key` com uma chave de API do PromptShield (`POST /v1/api-keys`, papel admin; ou a que `python -m app.cli create-tenant` imprime). Use **Test connection**: deve voltar **allow**.
5. No Claude: **Mode = Shadow mode**; no PromptShield: modo **Sombra** (padrão). Acompanhe os números do console por alguns dias.
6. Só então passe para aplicar, política por política (cada política tem o próprio modo, que também nasce em monitorar). No Claude, escolha **Failure handling** pensando no pior caso: com "Block the request", uma queda nossa bloqueia a organização inteira até o disjuntor resetar.
7. Libere no firewall `160.79.106.0/24` (origem das requisições). Isso não substitui a verificação de assinatura.

Variáveis da API: `INFERENCE_HOOK_BUDGET_MS` (padrão 3000, abaixo dos 5000 ms padrão da Anthropic), `INFERENCE_HOOK_MAX_BODY_BYTES`, `INFERENCE_HOOK_PREVIOUS_SECRET_MINUTES`. O modo de falha do nosso lado (erro interno ou orçamento estourado) é o `failure_mode` do tenant; em sombra sempre permite.

## Testes

```bash
make test        # inclui 14 testes da biblioteca e 23 do endpoint (com PostgreSQL)
```
