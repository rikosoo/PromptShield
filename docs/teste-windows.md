# Teste na sua máquina Windows (passos 0, 1 e parte do 3)

Guia para rodar o roteiro (`docs/roteiro-testes-reais.md`) em um Windows. **Nada aqui foi executado no Windows**: o desenvolvimento foi feito em Linux. Onde algo falhar, anote o erro: é exatamente o que o teste procura.

Use só dados sintéticos e contas de teste. Tudo roda em `localhost`, então nada sai da sua máquina, exceto o que o Claude Code e os sites já enviam normalmente.

## O que você precisa

| Item | Para quê | Observação |
|---|---|---|
| Docker Desktop (com WSL 2) | passo 0: API, banco, console | alternativa sem Docker: seção "Sem Docker" |
| Git | clonar o repositório | |
| Python 3.12 ou mais novo | hook do Claude Code | só biblioteca padrão |
| Claude Code 2.1.295 ou mais novo | passo 1 | `claude --version` |
| Chrome ou Edge | passo 3 | perfil separado só para teste |
| Node.js 20 ou mais novo | build da extensão | |

O `make` não existe no Windows. Os comandos abaixo são os equivalentes, em PowerShell.

## Passo 0: subir tudo

```powershell
git clone https://github.com/rikosoo/AgenticIASec.git
cd AgenticIASec
git checkout claude/wonderful-hamilton-9dsk59
Copy-Item .env.example .env
```

Edite o `.env` e defina `OIDC_MODE=mock`, `OIDC_MOCK_SECRET` (qualquer texto de 32+ caracteres) e `AUTH_MODE=mock` (já é o padrão do exemplo). Troque as duas senhas do banco por qualquer valor local.

```powershell
docker compose up --build
```

Em outro terminal, crie um tenant de teste e os dados sintéticos:

```powershell
docker compose exec api python -m app.cli create-tenant --name "Empresa Teste" --slug teste --admin-email admin@teste.example
docker compose exec api python -m app.cli seed-demo --slug teste
```

A chave `ps_...` aparece **uma única vez**: copie e guarde.

Conferir:

```powershell
curl.exe http://localhost:8000/health
```

Abra <http://localhost:3000>, entre com `admin@teste.example` (modo mock). Esperado: console com o selo "dados de exemplo".

Teste o envio de um evento com a chave (CPF sintético válido, `529.982.247-25`): use o `curl` do `README.md` (no PowerShell use `curl.exe` e aspas simples no JSON, ou salve o JSON em arquivo e use `-d "@arquivo.json"`).

Registre no registro de evidências: se subiu de primeira, mensagens de erro, tempo.

### Sem Docker (se o Docker Desktop der problema)

Precisa de PostgreSQL 16 instalado. Crie o ambiente Python (`python -m venv .venv`, `.venv\Scripts\pip install -e packages/detection -e packages/adapters/inference_hooks -e apps/api`), configure `DATABASE_URL` e `ADMIN_DATABASE_URL` como no `docker-compose.yml`, rode `alembic upgrade head` em `apps/api` e `uvicorn app.main:app`. O console roda com `npm ci` e `npm run dev` em `apps/web`. Este caminho é menos testado: registre o que falhar.

## Passo 1: hook do Claude Code no Windows

> **Mais simples:** `pip install -e packages\adapters\claude_code_hook` e depois `python -m promptshield_claude_hook setup` (menu interativo, ver `packages/adapters/claude_code_hook/README.md`). O texto abaixo é o caminho manual.

O instalador é só para Linux e macOS. No Windows, faça à mão, **sem mexer na política da máquina**, usando `--settings`.

1. Instale o hook:

```powershell
python -m pip install -e packages\adapters\claude_code_hook
```

> Atalho: `packages\adapters\claude_code_hook\install\install-user.ps1 -DryRun` mostra o que seria feito; sem `-DryRun` ele faz os passos 1 a 4 abaixo (por usuário, sem administrador) e cria `claude-ps.cmd`. **Não foi executado em Windows real**: se falhar, siga o manual e me mande o erro.

2. Crie `C:\ps-teste\hook.json` (troque a chave):

```json
{
  "api_url": "http://localhost:8000",
  "api_key": "ps_COLE_A_CHAVE_AQUI",
  "fail_mode": "open",
  "timeout_seconds": 3,
  "integration_status": "partial",
  "department": "Teste"
}
```

3. Crie `C:\ps-teste\settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python", "args": ["-m", "promptshield_claude_hook"], "timeout": 10 }] }],
    "PreToolUse":  [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python", "args": ["-m", "promptshield_claude_hook"], "timeout": 10 }] }],
    "PostToolUse": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python", "args": ["-m", "promptshield_claude_hook"], "timeout": 10 }] }]
  }
}
```

Se `python` não for o comando certo na sua máquina (por exemplo `py`), ajuste `command`.

4. Defina o caminho da configuração na sessão do PowerShell (o Windows não tem caminho padrão) e teste a conexão:

```powershell
$env:PROMPTSHIELD_HOOK_CONFIG = "C:\ps-teste\hook.json"
python -m promptshield_claude_hook check
```

Esperado: configuração válida e conexão com a API.

5. Rode o Claude Code a partir da mesma sessão, em uma pasta descartável:

```powershell
mkdir C:\ps-teste\projeto; cd C:\ps-teste\projeto
claude --settings C:\ps-teste\settings.json
```

Casos (política em **monitorar**, padrão, então nada deve ser bloqueado):

| Caso | O que digitar | Esperado no console |
|---|---|---|
| Prompt | `o CPF do cliente de teste é 529.982.247-25` | evento do tipo prompt, `pii`, texto mascarado, `would_decide` com decisão hipotética |
| Ferramenta | `liste os arquivos da pasta` | `tool_call` e `tool_result` (se `PostToolUse` funcionar) |
| Comando suspeito | `rode: Get-Content $HOME\.aws\credentials` (arquivo pode não existir) | `tool_call` com `leitura_env` |
| API fora | `docker compose stop api` e enviar outro prompt | Claude Code segue normal; arquivo de fila local com **só metadados** em `%USERPROFILE%\.promptshield\` |

Depois, para testar bloqueio: no console, crie uma política em modo **aplicar** (enforce) para a categoria de segredo e repita com `use a chave AKIAEXEMPLOEXEMPLO123 no deploy`. Esperado: prompt bloqueado com mensagem.

Não testados antes e que você pode observar: se o hook roda de fato (`python -m` pelo Claude Code no Windows), a acentuação nas mensagens no terminal do Windows, e o comportamento com `fail_mode: closed` mais `onFailure: "block"` (adicione `"onFailure": "block"` ao hook no `settings.json` e derrube a API).

## Passo 3 (parte): extensão em Chrome/Edge

```powershell
cd apps\extension
npm ci
npm run build:dev
```

No navegador (perfil de teste): `edge://extensions` ou `chrome://extensions`, "Modo do desenvolvedor", "Carregar sem compactação", escolha `apps\extension\dist\dev`. O build `dev` lê a configuração de `chrome.storage.local.devConfig` (detalhes e formato no `apps/extension/README.md`). Aponte para `http://localhost:8000` com a chave do tenant e permita `chatgpt.com` e `claude.ai`.

Abra o site com uma conta de teste, digite um prompt com o CPF sintético e veja o diálogo; repita com Enter, com o botão e colando. Os seletores nunca foram conferidos nas páginas reais: **o mais provável é que algo falhe aqui**. Anote qual campo ou botão não foi encontrado e, se puder, o HTML do elemento (sem conteúdo seu), para ajustarmos.

## O que não dá para testar só na sua máquina

OIDC com provedor real (passo 2), inference hooks (passo 4, exigem um tenant Claude Enterprise com acesso de administrador e uma URL pública com HTTPS), Teams/Slack/SMTP/SIEM reais (passo 5). Se quiser começar pelo passo 2, diga qual provedor de identidade você tem (Google, Microsoft Entra, Okta, Auth0 etc.).

## Como me devolver o resultado

Cole aqui, por passo, o que passou, o que falhou e o texto exato dos erros. Não cole chaves nem conteúdo real. Com isso eu corrijo o código e a documentação e atualizo o registro de evidências.
