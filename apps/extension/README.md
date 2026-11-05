# Extensão PromptShield para Chrome e Edge (Manifest V3)

Monitora, **com aviso visível ao usuário**, o texto enviado a **ChatGPT web** e **Claude.ai** e aplica a decisão da política da empresa.
Classificação da integração: **EXPERIMENTAL** (ver "Limites e o que não foi verificado").

## O que ela faz

- Roda **só** nos domínios configurados (padrão embutido: `chatgpt.com` e `claude.ai`). Em qualquer outro site não injeta nada, não mostra nada e não chama a API.
- Lê o texto **apenas no momento do envio** (Enter ou clique em enviar). Nunca tecla por tecla.
- Mostra sempre um indicador no canto da tela ("PromptShield: monitoramento ativo") com link para a **política de uso de IA da empresa**.
- Envia o evento (texto, usuário, app) à API da empresa, nunca a terceiros. A chave da API fica só no service worker; o content script não a recebe.
- Aplica a decisão: **permitir** (envia), **avisar** antes do envio, **mascarar com confirmação** (mostra a versão mascarada e só envia se o usuário confirmar), **bloquear**, **pedir justificativa** (mínimo de 10 caracteres, gravada na auditoria).
- API fora do ar: `fail_mode: open` envia e avisa na tela; `closed` bloqueia com mensagem. Chave errada conta como falha.
- Se o site mudar o HTML e o campo de prompt não for mais encontrado, o indicador **avisa** que o monitoramento pode estar inativo.

Cada site é um módulo separado em `src/sites/` (campo de prompt, botão de enviar, tecla de envio). Se o site mudar, só o módulo dele quebra.

## Desenvolver e testar

```bash
cd apps/extension
npm ci
npm run lint            # tsc
npm test                # vitest: configuração, decisões, evento, módulos de site, build de produção
npm run build:dev       # dist/dev: acrescenta página local de teste e configuração em storage.local
CHROMIUM_PATH=/caminho/do/chromium npm run test:e2e     # Playwright: extensão real em Chromium, API simulada
```

Teste ponta a ponta contra a **API real** com PostgreSQL (CORS, formato da resposta, justificativa na auditoria):

```bash
(cd apps/extension && npm run build:dev)
DATABASE_URL_TEST=... CHROMIUM_PATH=... .venv/bin/pytest apps/api/tests/test_extension_e2e.py
```

Carregar em modo desenvolvedor (`chrome://extensions` ou `edge://extensions`, "Modo do desenvolvedor", "Carregar sem compactação"): escolha `dist/prod` para ver o build de produção. Sem política gerenciada ela fica sem configuração (e avisa na tela). O build `dist/dev` lê a configuração de `chrome.storage.local.devConfig` (só para teste).

## Configuração gerenciada (produção)

A extensão declara um esquema (`managed_schema.json`) e lê `chrome.storage.managed`:

| Chave | Descrição |
|---|---|
| `api_url` | URL da API, **https** obrigatório em produção |
| `api_key` | chave de API do coletor (escopo `ingest`) |
| `user_id` | identificador, se o perfil do navegador não informar e-mail |
| `department` | departamento |
| `domains` | lista que **restringe** os domínios embutidos (nunca amplia) |
| `policy_url` | endereço da política de uso de IA (link no indicador) |
| `fail_mode` | `open` ou `closed` |
| `timeout_ms` | espera pela API (500 a 15000; padrão 4000) |

Além disso, a extensão busca `GET /v1/extension-config` na API (a cada 30 minutos): lista de domínios do tenant, link da política e modo de falha. **A API só restringe** domínios; o valor gerenciado vence nos demais campos. O administrador altera esses valores com `PATCH /v1/tenant`.

**API e CORS.** A extensão não tem permissão de host; quem chama é o service worker, então a API precisa liberar a origem da extensão: `CORS_ALLOWED_ORIGINS=chrome-extension://<ID-da-extensão>`. Sem essa variável nenhuma origem é liberada.

### Instalação forçada e entrega da configuração

**Estado da verificação (leitura em 2026-10-14).** Os sites de documentação do Chrome e do Edge estavam bloqueados neste ambiente. Confirmado em fonte primária: o formato da `ExtensionInstallForcelist`, lido na definição de política do Chromium (cada item é o ID da extensão, opcionalmente seguido de `;` e a URL do manifesto de atualização; em Windows exige domínio do AD, Azure AD ou Chrome Enterprise Core para extensões fora da Chrome Web Store). O restante abaixo vem de resumos de busca e de memória e está **A VERIFICAR** antes de ir a produção.

| Mecanismo | O que fazer | Status |
|---|---|---|
| Chrome, GPO/registro (Windows) | `ExtensionInstallForcelist` com `<ID>;<URL de atualização>`; valores em `HKLM\Software\Policies\Google\Chrome\3rdparty\extensions\<ID>\policy` | forcelist confirmado; caminho `3rdparty` por resumo de busca (cita a documentação do Chromium) |
| Edge, GPO/Intune (Windows) | `ExtensionInstallForcelist` do Edge e a configuração em `HKLM\Software\Policies\Microsoft\Edge\3rdparty\extensions\<ID>\policy` | **A VERIFICAR** (caminho por analogia) |
| Intune | Catálogo de configurações do Edge/Chrome (forcelist) e política de extensão com a configuração em JSON | **A VERIFICAR** |
| Jamf (macOS) | Perfil de configuração com o domínio `com.google.Chrome` ou `com.microsoft.Edge`, chaves `ExtensionInstallForcelist` e `3rdparty` | **A VERIFICAR** |
| Linux (Chrome) | JSON em `/etc/opt/chrome/policies/managed/` com a chave `3rdparty` | **A VERIFICAR** |

Exemplo do conteúdo gerenciado (valores sintéticos), a ser entregue por um dos mecanismos acima:

```json
{ "api_url": "https://promptshield.empresa.example", "api_key": "ps_XXXXXXXX_...", "department": "Engenharia",
  "policy_url": "https://intranet.empresa.example/politica-ia", "fail_mode": "open" }
```

O ID da extensão precisa ser estável: na Chrome Web Store ele é fixado pela loja; ao hospedar o `.crx` por conta própria, fixe o ID com a chave de empacotamento (**A VERIFICAR** o procedimento). Confira o que o navegador carregou em `chrome://policy`.

Avisos de segurança: a `api_key` fica legível dentro do perfil do navegador (apenas envia eventos). Rotação de chaves entra na Etapa 9. Avise os colaboradores antes de ativar (LGPD): a extensão envia o texto dos prompts à API da empresa.

## Arquivos anexados

Ao anexar (seletor de arquivo, arrastar ou colar) num site monitorado, a extensão guarda **nome, tamanho e tipo** e os envia junto do próximo prompt (`content.attachments`). O conteúdo do arquivo nunca é lido. Um envio só com arquivo, sem texto, também é inspecionado (`kind: file_upload`). Limites: se o usuário remover o anexo na página antes de enviar, a extensão não percebe; vale como "anexado", não "enviado". Validado em Chromium com página simulada; **não** nos sites reais (A VERIFICAR).

## O que a extensão NÃO consegue ver

- **Respostas do modelo** (streaming ou não): a extensão nunca as lê.
- **Aplicativos desktop** (ChatGPT e Claude para computador) e **aplicativos móveis**.
- **Outros navegadores** (Firefox, Safari) e navegadores sem a política aplicada.
- **Perfis não gerenciados**: o usuário pode remover a extensão em perfil pessoal; em janela anônima ela só roda se a política permitir.
- **Anexos, imagens e voz**: só o texto do campo de prompt é lido.
- **Edição de mensagens antigas e outros campos** além do campo principal: os módulos de site cobrem o campo principal de envio.
- **Outros domínios** (`chat.openai.com` legado, outros assistentes): fora da lista embutida.
- **Conta pessoal ou corporativa do site**: a extensão não sabe, e envia `personal_account: false`.
- Uso via API ou por outra ferramenta (cobertos pelos outros adaptadores).

## Limites e o que não foi verificado

- **Os seletores de ChatGPT e Claude.ai não foram conferidos contra as páginas reais** (`chatgpt.com` é negado e `claude.ai` responde 403 ao ambiente de desenvolvimento). Os testes usam uma página local que imita o campo de prompt e o botão. Os módulos têm listas de alternativas, e o indicador avisa quando o campo some, mas só um teste manual nos sites reais promove esta integração de EXPERIMENTAL para REAL. **Checklist:** instalar o `dist/prod` em um perfil de teste, abrir cada site, digitar um prompt com CPF sintético e confirmar o diálogo; repetir com Enter e com clique.
- **Editores ProseMirror** (usados por ambos os sites, segundo meu conhecimento) são preenchidos com `execCommand("insertText")`; não testado nos sites reais.
- **CSP dos sites:** a interface usa shadow DOM, sem `innerHTML`, e folhas de estilo construídas (`adoptedStyleSheets`). Se a CSP de um site bloquear isso, o diálogo não aparece: **A VERIFICAR**.
- **Primeira leitura da política gerenciada** leva ~3 s no Chromium 141 testado; durante esse tempo o envio fica retido (nunca passa sem decisão).
- Os testes automáticos usam um Chromium 141 em modo `--headless=new` com o shadow DOM **aberto** (build de teste); em produção ele é fechado (checado no build).
