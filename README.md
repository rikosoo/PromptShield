# PromptShield

Plataforma B2B multi-tenant, um "Defender para IA": observa o uso de IA por funcionários e agentes (prompts, arquivos anexados, ações de agentes), classifica cada evento, calcula um risco explicável e aplica políticas (permitir, mascarar, bloquear, pedir justificativa). Contexto completo e princípios em [`CLAUDE.md`](CLAUDE.md).

```
sensor na máquina → evento universal → motor de detecção → política → console
(hook / extensão)   (um só formato)    (regras locais)      (começa só monitorando)
```

## Estado (honesto)

**Experimental, testado só com dados sintéticos e num servidor de teste.** Não está pronto para vender sem as pendências abaixo.

| Funciona e foi visto rodando | Ainda não |
|---|---|
| Servidor na AWS (Docker), console, login de teste (mock) | Login real (OIDC) com provedor de verdade |
| Instalação do sensor com uma linha no Windows; hook do Claude Code | HTTPS e domínio (hoje HTTP; o hook envia o texto original à API) |
| Extensão no ChatGPT web e no Gemini web (vistas em site real) | Seletores de Claude e Copilot na web; Codex CLI (o hook falhou com código 1 no primeiro teste real; corrigido, falta ver enviando); apps de desktop não são cobertos |
| Detecção por regras, histórico de prompts, revisão humana, licença, suspensão | Executável assinado; instalação por Intune/GPO; teste em Mac |
| CI com testes de API, motor, console, extensão, serviço de licenças e `docker compose` | Pentest independente; revisão jurídica; cobrança |
| Licenciamento on-premise (ativação por código, autorização assinada, estados), testado em processo e em banco real | Ensaio entre duas máquinas e com um cliente de verdade ([`docs/licenciamento.md`](docs/licenciamento.md)) |

## Como usar (resumo)

1. **Servidor** (uma VM Linux com Docker): `./infra/vm-setup.sh --admin-email voce@empresa.com`. Guia: [`docs/guia-simples.md`](docs/guia-simples.md), [`docs/teste-vm.md`](docs/teste-vm.md) e, para a AWS (EC2) com os cliques do console, [`docs/instalacao-aws.md`](docs/instalacao-aws.md).
2. **Console:** `http://IP_DA_VM:3000`. Em **Dispositivos**, crie um token de matrícula.
3. **Sensor em cada máquina** (uma linha, sem administrador):

   ```powershell
   $env:PS_API='http://IP_DA_VM:8000'; $env:PS_TOKEN='pse_...'; irm "$env:PS_API/sensor/install.ps1" | iex
   ```

   O instalador pergunta quais IAs monitorar, por números (1 ChatGPT web, 2 Copilot web, 3 Gemini web, 4 Claude web, 5 Claude Code CLI, 6 Codex CLI, 7 GitHub Copilot CLI). Estado de cada uma: [`docs/guia-ias.md`](docs/guia-ias.md). Windows: [`docs/teste-windows.md`](docs/teste-windows.md).
4. **Extensão do navegador:** um clique seu, uma vez (`chrome://extensions` → Carregar sem compactação → `~/.promptshield/extension`).
5. **Atualizar o servidor:** `git pull` e `docker compose up -d --build` (as migrações rodam sozinhas ao subir). Faça backup antes ([`docs/operacao.md`](docs/operacao.md)); nunca use `docker compose down -v`.

## O que o console mostra

O menu é agrupado em cinco áreas: **Visão geral**, **Incidentes**, **Usuários e grupos**, **Políticas** e **Administração**. Em **Usuários e grupos**: *Risco por usuário* e *Grupos*. Em **Políticas**: *Exceções*, *Domínios permitidos* e *Palavras-chave*.

| Tela | Para quê |
|---|---|
| Visão geral | totais, risco alto, série por dia, departamentos, ferramentas e **confiabilidade**: taxa de falso positivo / faltou pegar (revisão humana) e **cobertura dos coletores** (por IA: capturando, parou, aguardando), para o painel não passar falsa sensação de segurança |
| **Todos os prompts** | tudo que foi capturado, quem escreveu, filtros por pessoa, palavra-chave (prompt ou nome de arquivo), ferramenta, categoria, decisão, departamento, período, revisão; exportação CSV (admin/auditor, auditada) |
| Análise de prompts | do mais arriscado ao menos, com sinais clicáveis (segredos, o que as pessoas pedem) |
| Incidentes | fila e triagem; texto original só com justificativa e auditoria |
| **Qualidade da detecção** | revisão humana ("correta / falso positivo / faltou pegar") e precisão estimada por categoria; exportação auditada |
| Risco por usuário, Alertas e SIEM, Relatórios | score explicável, webhook/Slack/Teams/e-mail/CEF, PDF e CSV |
| **Sensores** | **painel de todas as máquinas com sensor**: nome da máquina, sistema, **quais IAs estão habilitadas em cada uma** e se chegaram eventos (capturando / aguardando / manual), último usuário (e quantas pessoas usaram a máquina), última atividade, **alertas** (nunca enviou, inativo, extensão sem evento, sensor desatualizado), filtros por máquina, IA, situação e alerta, atalho para os prompts do sensor e **exportação em CSV** (admin/auditor, auditada) |
| **Grupos** | grupos de pessoas gerenciados no servidor (um sensor não consegue se declarar de um grupo); usados no escopo das políticas |
| **Exceções** | a política deixa de valer para uma pessoa ou grupo, **com motivo e validade obrigatórios** (máx. 365 dias); o evento segue analisado e marcado como «exceção»; criar e revogar é auditado |
| **Palavras-chave** | palavras que o administrador quer vigiar: todo prompt que contém a palavra gera um alerta; a pontuação é opcional (vazia = a calculada pelo algoritmo; preenchida = substitui a calculada, com o motivo registrado). Nunca bloqueia |
| **Domínios permitidos** | destinos aprovados (com subdomínios) que não geram alerta de rede externa; **também deixam de ser sinalizados como destino de envio de dados**, por isso só o administrador mexe |
| Dispositivos | tokens de matrícula, cobertura por ferramenta, licença, revogação |
| Políticas, Privacidade e segurança, Piloto, Inference hooks | políticas em modo monitorar ou aplicar, retenção, mapa de dados, piloto de 30 dias |

## Monitoramento passivo e motor 2.0

O PromptShield **só observa, analisa, registra e alerta**: nunca bloqueia, altera ou interrompe um prompt (servidor, sensores e extensão). A análise reconhece dados sensíveis declarados em linguagem natural (pt, en, es), correlaciona indicadores e devolve um resultado padronizado com severidade 0–24 baixo, 25–49 moderado, 50–69 alto e 70–100 crítico. Diagnóstico, arquitetura, medições antes/depois e limites: [`docs/motor-2.0.md`](docs/motor-2.0.md).

## O que ele detecta (e o que não)

30 categorias em [`packages/taxonomy`](packages/taxonomy): dados sensíveis (CPF, CNPJ, RG, cartão, chaves, senhas...), código e engenharia, ataques à IA (injection, jailbreak, extração de system prompt), ações de agente (comandos destrutivos, leitura de credenciais, rede externa...) e negócio. **Arquivos anexados:** só nome, tamanho e tipo (nunca o conteúdo); o nome gera risco (`.env`, `folha_pagamento`...).

A detecção é **por regras locais**, sem LLM externo e sem modelo treinado. Medida honesta em textos sintéticos que não guiaram nenhum ajuste: **cerca de 85% de acerto exato** (conjunto D: 86,2%). Os 95% a 98% dos conjuntos A, B, C e E são otimistas, porque eles guiaram os ajustes. Em dados reais pode ser pior. Catálogo com exemplos rodados e erros conhecidos: [`docs/o-que-detecta.md`](docs/o-que-detecta.md). Método, números e limites: [`docs/deteccao.md`](docs/deteccao.md).

## Contrato, licença e suspensão (só o fornecedor)

- Licença por empresa: limite de **máquinas ativas nos últimos 45 dias** e validade (`python -m app.cli set-license`). Só barra novas matrículas.
- `python -m app.cli tenants` lista as empresas; `suspend --slug X --reason "..."` e `resume --slug X` suspendem e reativam. Suspensa: coletores recusados, console só lê e exporta, nada é apagado, funcionários não são afetados (sensores em falha aberta). O console mostra faixa de aviso (amarela 15 dias antes do vencimento, vermelha depois). Nunca automático. Detalhes e o que falta (cobrança, apagar a empresa, painel): [`docs/operacao.md`](docs/operacao.md).
- **Licenciamento on-premise** (servidor do cliente): o fornecedor cadastra contrato e gera um **código de ativação** de uso único; o administrador o informa no console (**Licença**); a instalação cria a própria identidade (chave Ed25519), o serviço de licenças vincula o contrato à chave pública dela e devolve uma **autorização assinada**; o worker renova sozinho (por exemplo, uma vez por dia; cada autorização vale poucos dias). Há **dois prazos** (contrato e autorização local; a autorização nunca passa do contrato mais a tolerância) e cinco estados: ativo, sem contato, em tolerância, expirado, encerrado. Nenhum estado apaga dados; se a inspeção parar, console e sensores avisam. Desligado por padrão (`LICENSE_MODE=off`). Desenho, segurança, operação e **como validar**: [`docs/licenciamento.md`](docs/licenciamento.md).
- Domínio, subdomínio por cliente e executável assinado: [`docs/dominio-e-assinatura.md`](docs/dominio-e-assinatura.md) (nada contratado).

## Mapa do repositório

| Pasta | O que tem |
|---|---|
| `apps/api` | FastAPI: ingestão, políticas, incidentes, auditoria, revisão humana, licença; multi-tenant com RLS; migrações Alembic 0001 a 0019 |
| `apps/web` | console Next.js (claro por padrão, escuro por alternância); ver o README da pasta |
| `apps/extension` | extensão Chrome/Edge (EXPERIMENTAL; ver o README da pasta) |
| `packages/detection` | motor de detecção (biblioteca pura) e scripts de avaliação |
| `packages/licensing` | licenciamento: assinatura Ed25519, autorização, pedidos da instalação e máquina de estados (biblioteca pura) |
| `apps/licensing` | **serviço de licenças do fornecedor** (contratos, códigos, instalações, auditoria, CLI); não vai para o servidor do cliente |
| `packages/taxonomy` | as 30 categorias |
| `packages/adapters/claude_code_hook` | sensor: hooks do Claude Code e do GitHub Copilot CLI, instalador, importação do histórico |
| `packages/adapters/inference_hooks` | inference hooks do Claude Enterprise |
| `infra/` | `vm-setup.sh`, `expose.sh`, `backup.sh`, `restore.sh` |
| `tests/fixtures` | dados **sintéticos** e os conjuntos de avaliação (A a H) |

## Documentação

| Documento | Assunto |
|---|---|
| [`docs/guia-simples.md`](docs/guia-simples.md), [`docs/guia-ias.md`](docs/guia-ias.md) | instalar servidor e sensor; escolher IAs |
| [`docs/teste-vm.md`](docs/teste-vm.md), [`docs/teste-windows.md`](docs/teste-windows.md), [`docs/roteiro-testes-reais.md`](docs/roteiro-testes-reais.md) | testes em VM e Windows; roteiro de validação real |
| [`docs/implantacao-empresa.md`](docs/implantacao-empresa.md) | instalar na empresa inteira (parcial) |
| [`docs/operacao.md`](docs/operacao.md) | variáveis, backup e restauração, retenção, chaves, suspensão |
| [`docs/licenciamento.md`](docs/licenciamento.md) | licenciamento on-premise: fluxo, prazos, estados, segurança, operação e validação |
| [`docs/cobranca.md`](docs/cobranca.md) | **proposta** (nada construído): plano de cobrança, linha do tempo de inadimplência, escada de limitação e arquitetura |
| [`docs/vistoria-seguranca.md`](docs/vistoria-seguranca.md), [`docs/ameacas.md`](docs/ameacas.md) | vistoria (OWASP Top 10:2021), modelo de ameaças |
| [`docs/lgpd.md`](docs/lgpd.md), [`docs/piloto.md`](docs/piloto.md) | modelos para advogado; piloto de 30 dias |
| [`docs/arquitetura.md`](docs/arquitetura.md), [`docs/decisoes.md`](docs/decisoes.md), [`docs/viabilidade.md`](docs/viabilidade.md) | arquitetura, decisões (uma linha cada), captura por ferramenta |
| [`docs/siem.md`](docs/siem.md), [`docs/inference-hooks.md`](docs/inference-hooks.md), [`docs/claude-code-hooks.md`](docs/claude-code-hooks.md) | alertas e CEF, inference hooks, hooks do Claude Code |

## Requisitos

Docker com Compose (para `make up`). Para `make test` e `make lint` sem Docker: Python 3.12 ou superior e Node 22. Para os testes de ponta a ponta do console e da extensão (Playwright): Chromium (`CHROMIUM_PATH`).

## Passo a passo

```bash
git clone <este repositório> && cd PromptShield
make up        # cria .env a partir de .env.example, sobe db, api e web
```

Depois de subir:

- API: <http://localhost:8000/health> (responde `{"status":"ok"}`) e <http://localhost:8000/docs>
- Console: <http://localhost:3000> (login por OIDC; para desenvolvimento veja `apps/web/README.md`, modo `mock`, e `seed-demo` para dados sintéticos)

Para parar: `Ctrl+C` e `make down`.

Segredos: `.env` fica fora do git. Troque a senha do banco em `.env` e na `DATABASE_URL` se for expor a porta 5432.

## Testes e lint

```bash
make test      # pytest (api, detection, hooks) e vitest (web, extensão)
make lint      # ruff (inclui regras de segurança) e eslint/tsc
make audit     # npm audit e pip-audit
```

O teste de migração roda em um Postgres de verdade quando `DATABASE_URL_TEST` está definida; sem ela é pulado.

```bash
DATABASE_URL_TEST=postgresql+psycopg://usuario:senha@localhost:5432/banco_de_teste make test
```

O banco de teste precisa ser UTF8; o teste cria e remove a tabela `tenants`.

## API de ingestão (Etapa 3)

Documentação interativa em <http://localhost:8000/docs> (OpenAPI em `/openapi.json`).

1. Crie um tenant (com administrador, uma chave de API e as políticas padrão, **todas em modo monitorar**):

   ```bash
   docker compose exec api python -m app.cli create-tenant \
     --name "Empresa Exemplo" --slug exemplo --admin-email admin@empresa-exemplo.com.br
   ```

   A chave `ps_...` aparece uma única vez. Só o hash dela fica no banco.

2. Envie um evento sintético com CPF:

   ```bash
   curl -s -X POST http://localhost:8000/v1/events \
     -H "X-API-Key: ps_SUA_CHAVE" -H "Content-Type: application/json" -d '{
       "event_id": "7d1f6d0e-3b5e-4f3a-9c55-0a1b2c3d4e5f",
       "occurred_at": "2026-10-14T12:00:00Z",
       "source": {"channel": "agent_hook", "app": "claude_code", "integration_status": "partial"},
       "actor": {"user_id": "rafael.moreira", "department": "Engenharia"},
       "kind": "prompt",
       "content": {"text": "Cliente CPF 529.982.247-25, pode revisar o contrato?"}
     }'
   ```

   Resposta (resumida), verificada contra a API rodando com PostgreSQL 16:

   ```json
   {"decision": "allow", "would_decide": "mask", "enforced": false,
    "masked_text": "Cliente CPF ***.***.***-25, pode revisar o contrato?",
    "categories": [{"id": "pii", "confidence": 0.97}], "risk": {"score": 58, "...": "..."}}
   ```

   Em modo monitorar a decisão devolvida é sempre `allow`; `would_decide` mostra o que a política faria. Repetir o mesmo `event_id` devolve a mesma resposta (`"duplicate": true`) sem gravar de novo.

3. Console: `OIDC_MODE=mock` (só desenvolvimento) habilita `POST /dev/token` com `{"email": "..."}`; use o token como `Authorization: Bearer`. O e-mail precisa existir em `users`. Papéis: `admin`, `analista`, `auditor`, `leitura`. Para produção use `OIDC_MODE=oidc` com `OIDC_ISSUER`, `OIDC_AUDIENCE` e `OIDC_JWKS_URL` (**não testado contra um provedor real**, só com chaves geradas nos testes).

### Como o isolamento entre tenants funciona

Todas as tabelas de dados têm `tenant_id` e row-level security forçada. A API conecta com o papel `promptshield_app` (sem superuser e sem `BYPASSRLS`) e, a cada transação, define `app.tenant_id`. Sem essa variável, nenhuma linha é visível. A autenticação usa duas funções `SECURITY DEFINER` (`auth_api_key`, `auth_user_by_email`), as únicas que cruzam tenants.

Limite honesto: o papel da aplicação consegue executar `SET app.tenant_id`. O RLS protege contra consulta sem filtro, bug de código e SQL fixo; não protege contra quem já executa SQL arbitrário com esse papel. `audit_log` é só de inserção (gatilho no banco), até para o dono.

### Testes da API

```bash
DATABASE_URL_TEST=postgresql+psycopg://usuario:senha@localhost:5432/banco_de_teste make test
```

O usuário precisa ser dono do banco (cria o papel `promptshield_app`) e o banco precisa ser UTF8. O teste recria o esquema (`alembic downgrade base` e `upgrade head`) e apaga os dados entre testes: **nunca aponte para um banco com dados**.

## Alertas, SIEM e relatórios (Etapa 7)

O serviço `worker` do compose entrega a fila de notificações e gera relatórios agendados (`python -m app.worker`, ou `--once`). Canais, regras, formatos e o estado de cada integração (Teams é EXPERIMENTAL e A VERIFICAR; e-mail e Slack são PARCIAIS): [`docs/siem.md`](docs/siem.md). Para e-mail, configure `SMTP_*` no `.env`.

## Inference hooks do Claude Enterprise (Etapa 8)

Endpoint `POST /v1/inference-hook` e tela **Inference hooks** no console. **Depende do plano Claude Enterprise e de uma funcionalidade em beta da Anthropic (o suporte também é beta).** O protocolo foi lido na documentação oficial e o endpoint é testado com requisições simuladas conforme essa documentação; **nunca foi chamado por um tenant Enterprise real** (PARCIAL). Nasce em modo **sombra** (sempre permite e registra o que teria feito). Passo a passo do administrador do cliente, requisitos (HTTPS na porta 443, certificado público) e latência medida: [`docs/inference-hooks.md`](docs/inference-hooks.md) e o README de [`packages/adapters/inference_hooks`](packages/adapters/inference_hooks/README.md).

## Privacidade, segurança e piloto (Etapa 9)

- **Privacidade por padrão:** guarda só texto com identificadores mascarados; texto livre de saúde **não é guardado**; o original é opt-in, cifrado e apagado mais cedo; retenção configurável com job diário; acesso e eliminação por titular; mapa de dados por tenant. Documento jurídico (**modelo para revisão de advogado**, LGPD, GDPR e EUA): [`docs/lgpd.md`](docs/lgpd.md).
- **Segurança:** modelo de ameaças [`docs/ameacas.md`](docs/ameacas.md); limite de requisições por credencial, rotação de chaves, cabeçalhos de segurança, logs sem conteúdo; `make audit` (dependências) e as regras de segurança no `make lint`.
- **Operação:** backup e restauração testados (`infra/backup.sh`, `infra/restore.sh`), chaves, retenção, métricas: [`docs/operacao.md`](docs/operacao.md).
- **Piloto de 30 dias:** roteiro, checklist e métricas em [`docs/piloto.md`](docs/piloto.md); tela **Piloto** e relatório final em PDF.
