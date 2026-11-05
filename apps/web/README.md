# Console web (Etapas 6 a 9)

Next.js 16, React, TypeScript e Tailwind v4. Tema claro por padrão, com alternância para escuro. Todos os dados vêm da API real; nada é fixo no código.

Telas: visão geral, análise de prompts (painel das 30 categorias que filtra ao clicar), incidentes (fila, detalhe com linha do tempo, evidência mascarada e texto original só com justificativa e auditoria) e políticas (criar/editar, escopo, modo, simulação sobre eventos passados). Etapa 7: risco por usuário e departamento (com o aviso "indicador de risco, requer revisão humana"), alertas e canais de notificação/SIEM (só o administrador configura) e relatórios PDF/CSV com agendamento. Veja `docs/siem.md`. Etapa 9: telas **Piloto** (métricas, amostra de revisão, relatório final; `docs/piloto.md`) e **Privacidade e segurança** (mapa de dados, retenção, categorias sem guarda de texto, direitos do titular, chaves de API; `docs/lgpd.md`) e cabeçalhos de segurança (`lib/security-headers.ts`). Etapa 8: tela **Inference hooks** (modo sombra/aplicar, segredo de assinatura, números das últimas 24 h, passo a passo; `docs/inference-hooks.md`).

## Como funciona o acesso à API

O navegador **nunca** fala direto com a API nem guarda token em JavaScript. O console é um BFF:

- login grava o token em cookie `ps_session` (`httpOnly`, `SameSite=Lax`, `Secure` quando `PUBLIC_BASE_URL` é https);
- `/api/proxy/v1/...` repassa para a API com o token. Só caminhos `/v1/...` passam. Mutações exigem `X-Requested-With: promptshield` e `Origin` igual ao `Host` (proteção contra CSRF).

**Seleção de tenant:** não existe tela. Cada e-mail pertence a um único tenant, que a API resolve a partir do e-mail no login. Se um mesmo e-mail precisar de vários tenants, é preciso mudar o modelo (decisão em `docs/decisoes.md`).

## Variáveis de ambiente (servidor do console)

| Variável | Para quê |
|---|---|
| `API_INTERNAL_URL` | endereço da API visto pelo servidor do console (padrão `http://localhost:8000`) |
| `AUTH_MODE` | `mock` (só desenvolvimento: formulário de e-mail, usa `/dev/token` da API) ou `oidc` (padrão) |
| `PUBLIC_BASE_URL` | URL pública do console; usada no redirect do OIDC e para ligar cookie `Secure` |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | provedor OIDC (Authorization Code + PKCE). `OIDC_CLIENT_SECRET` é opcional |

Na API: `OIDC_MODE=mock` com `OIDC_MOCK_SECRET` (32+ caracteres) para desenvolvimento, ou `OIDC_MODE=oidc` com `OIDC_AUDIENCE` igual ao `OIDC_CLIENT_ID` do console.

**O fluxo OIDC está implementado, mas NÃO foi testado contra um provedor real.** Só o modo mock foi exercitado.

## Dados de exemplo

```bash
cd apps/api
python -m app.cli create-tenant --name "Empresa Exemplo" --slug exemplo --admin-email admin@exemplo.example
python -m app.cli seed-demo --slug exemplo
```

`seed-demo` grava eventos **sintéticos** e marca o tenant como demonstração; o console mostra o selo "dados de exemplo" enquanto a marca existir.

## Desenvolvimento e testes

```bash
cd apps/web
npm ci
npm run dev
npm test                 # vitest (lib/: proxy, sessão, formatação)
npm run lint             # tsc --noEmit
DATABASE_URL_TEST=postgresql+psycopg://postgres@localhost:5432/ps_e2e \
CHROMIUM_PATH=/opt/pw-browsers/chromium npm run test:e2e
```

O e2e (Playwright) recria o schema em `DATABASE_URL_TEST` (**apaga o banco indicado**), semeia 300 eventos sintéticos, sobe a API real e o console (`next start`) e roda 20 cenários: login, análise de prompts, filtro por categoria, abrir incidente, original com justificativa, selo, simulação de política, isolamento entre tenants, risco por usuário, alertas e teste de webhook assinado contra um servidor local, relatórios baixados com os mesmos números do painel e verificação de acessibilidade (axe-core) nas telas.
