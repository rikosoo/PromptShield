# Adaptador do Claude Code

Hook de comando que o Claude Code chama em `UserPromptSubmit`, `PreToolUse` e `PostToolUse`. Converte a entrada em evento universal, envia a `POST /v1/events` e responde com a decisão. Só usa a biblioteca padrão do Python (3.9 ou mais novo).

Documentação do formato e do que foi verificado: [`docs/claude-code-hooks.md`](../../../docs/claude-code-hooks.md).

## Como se comporta

| Situação | Resultado |
|---|---|
| Política em **monitorar** (padrão) | a API devolve sempre `allow`: o Claude Code nunca é interrompido; a decisão hipotética fica no console |
| Política em **aplicar**, `block` | prompt bloqueado / ferramenta negada (`deny`) |
| `mask` ou `ask_justification` | em prompt: bloqueia e mostra a versão mascarada (o hook não pode reescrever o prompt); em ferramenta: pede confirmação (`ask`) |
| API fora do ar, `fail_mode: open` | segue; grava só **metadados** em `~/.promptshield/claude-hook-spool.jsonl` (nunca o conteúdo) |
| API fora do ar, `fail_mode: closed` | bloqueia, com mensagem |
| Timeout da API (`timeout_seconds`, padrão 3 s), chave errada, erro interno | tratado como "API fora do ar" |

O adaptador sempre termina com código 0 e JSON válido: nunca derruba o Claude Code. No fail-closed o instalador também define `onFailure: "block"` no hook (versão 2.1.295 ou mais nova), para cobrir o caso de o próprio processo travar.

## Jeito mais simples: o assistente `setup` (Windows, Linux e macOS)

```powershell
pip install -e packages/adapters/claude_code_hook      # uma vez, na pasta do repositório
python -m promptshield_claude_hook setup
```

Menu interativo, que você pode repetir quantas vezes quiser: 1 vincula o **Claude Code**; 2 **Codex** (indisponível: o formato dos hooks não pôde ser verificado, **A VERIFICAR**); 3 guia da **extensão** para ChatGPT e Claude no navegador; 4 abre o **console no navegador**; 5 testa a conexão; 6 remove o vínculo. Na primeira vez pergunta o endereço da API e a chave: você cola uma que já tem, abre o console no navegador (página Privacidade e segurança) para criar, ou deixa o assistente criar sozinho (só com o login de teste `OIDC_MODE=mock`).

- **GitHub Copilot CLI (opção 2, EXPERIMENTAL):** grava só o arquivo `~/.copilot/hooks/promptshield.json` (documentado como local de hooks de usuário). Formato lido em `github/docs`, `hooks-reference.md` (2026-10-17): eventos `userPromptSubmitted`, `preToolUse` e `postToolUse`, comandos `bash` e `powershell`. O hook de prompt só **monitora** (o Copilot descarta a saída desse evento); `preToolUse` pode negar ou pedir confirmação. Os nomes das ferramentas do Copilot não constam na página lida (**A VERIFICAR**); só testado com entradas simuladas. **Não cobre** o Copilot no VS Code nem sugestões em linha.
- O vínculo grava `~/.promptshield/hook.json` (lido sem variável de ambiente) e **acrescenta** os hooks ao `~/.claude/settings.json` do usuário, sem tocar nos hooks que já existem, com cópia de segurança e sem BOM. Antes de alterar, mostra o que será capturado e exige digitar `sim`.
- Vale para o Claude Code no terminal. A aba Code do app Desktop e a extensão do VS Code **leem os mesmos arquivos de configuração** (documentação oficial: "The desktop app reads the same settings files as the CLI"), mas a documentação não confirma que os hooks disparam lá: **A VERIFICAR**. O **chat comum** do app Claude Desktop não tem hooks e **não é coberto** (para isso, só o inference hook do Claude Enterprise, no servidor).
- Navegador não pode ser instalado nem logado por programa: a opção 3 mostra os passos. O "login no navegador" do assistente é o do console do PromptShield para criar a chave; pareamento automático por código de dispositivo não existe.

## Extensão do navegador pelo sensor (EXPERIMENTAL)

O `deploy` (e o instalador de uma linha) inclui a ferramenta `browser_extension`: baixa de `/sensor/extension.zip` a extensão (build `--sideload`, ID fixo, só `chatgpt.com` e `claude.ai`), confere o SHA-256, grava `promptshield-config.json` com a **chave desta máquina** e mostra os 3 passos no navegador. A extensão lê esse arquivo (a política gerenciada, se existir, vence). Testado em Chromium real contra a API real, mas com uma página **simulada** com os seletores do ChatGPT; os sites reais não foram testados.

## Instalação em massa (EXPERIMENTAL, nível de máquina)

Para o TI da empresa: no console (**Dispositivos**) o administrador cria um **token de matrícula** (revogável, com validade e limite de máquinas); o comando abaixo, rodado como administrador em cada máquina (por MDM, GPO ou script), troca o token por uma **chave própria da máquina**, grava a configuração de máquina e os hooks de política do Claude Code (`managed-settings.json`) e do Copilot CLI (`policy.d`):

```text
python -m promptshield_claude_hook deploy --api-url https://api.empresa --token pse_... --confirm-employees-notified
python -m promptshield_claude_hook deploy --uninstall --confirm-employees-notified
```

`--confirm-employees-notified` é obrigatório: o aviso aos empregados é obrigação do cliente. É idempotente, faz cópia de segurança e preserva hooks de terceiros. A chave da máquina fica legível pelos usuários locais (o hook roda como o usuário), só envia eventos e é revogável por máquina. **Nunca rodou em MDM real**, ainda exige Python na máquina (executável único assinado está decidido, mas não construído) e não instala a extensão do navegador. Ver `docs/implantacao-empresa.md`.

## Instalar em uma máquina de teste (Linux e macOS)

Pré-requisitos: `python3`, Claude Code, e uma chave de API do tenant (`python -m app.cli create-tenant ...`, ver README da raiz).

```bash
cd packages/adapters/claude_code_hook
sudo ./install/install.sh --api-url https://sua-api.exemplo --api-key ps_XXXX --fail-mode open --department Engenharia
PROMPTSHIELD_HOOK_CONFIG=/etc/promptshield/claude-code-hook.json /usr/local/lib/promptshield/promptshield-claude-hook check
```

Use `--dry-run` para ver o que será feito. O instalador mescla os hooks no `managed-settings.json` (mantém o que já existe e faz cópia `.bak-…`). Para remover: `sudo ./install/uninstall.sh`.

Windows: há um instalador **por usuário**, `install/install-user.ps1` (sem administrador, NÃO executado em Windows real; use `-DryRun` primeiro). Para política da máquina (`C:\Program Files\ClaudeCode\managed-settings.json`) não há instalador: use o exemplo em `examples/managed-settings.json` e ajuste o caminho do comando.

Avisos:
- A chave fica legível por todos os usuários da máquina (o hook roda como o usuário). Ela só envia eventos. Rotação de chaves entra na Etapa 9.
- O hook envia prompts e ações dos agentes. **Avise os colaboradores** antes de ligar.
- O hook não sabe se a conta é pessoal ou corporativa (o Claude Code não informa) e identifica o usuário pelo usuário do sistema operacional, salvo `user_id` na configuração.
- Textos acima de `max_text_chars` (200.000) são cortados antes do envio.
- O instalador **não** liga `allowManagedHooksOnly` (que bloquearia os hooks próprios do cliente) a menos que você passe `--managed-only-hooks`.

## Verificar em um Claude Code de verdade (checklist)

Sem alterar a política da máquina, use `--settings` com um arquivo de hooks (modelo em `examples/managed-settings.json`) e um arquivo de configuração do hook (`examples/claude-code-hook.json`):

```bash
export PROMPTSHIELD_HOOK_CONFIG=/caminho/hook.json
claude -p "use a chave AKIAEXEMPLOEXEMPLO123 no deploy" --settings /caminho/settings.json     # com a política de segredos em aplicar: bloqueado
claude -p "rode: cat ~/.aws/credentials" --settings /caminho/settings.json --allowedTools Bash  # com a política de leitura de credenciais em aplicar: ação negada
```

Resultado de 2026-10-14 com Claude Code 2.1.296: os dois casos foram bloqueados (detalhes e o que ficou sem testar em `docs/claude-code-hooks.md`).

## Importar o histórico local (EXPERIMENTAL)

Envia o que já está nas transcrições do Claude Code da máquina (`~/.claude/projects/<projeto>/<sessão>.jsonl`; no Windows `%USERPROFILE%\.claude\projects`). O local e a retenção (30 dias por padrão, `cleanupPeriodDays`) são documentados; **o formato dos registros não é**: foi lido o formato observado no Claude Code 2.1.x e precisa ser conferido a cada versão (registro que não bate é contado e ignorado).

```powershell
python -m promptshield_claude_hook import                       # SIMULAÇÃO: mostra contagens, não envia
python -m promptshield_claude_hook import --preview 5           # mostra os 5 primeiros textos no seu terminal
python -m promptshield_claude_hook import --since 2026-10-01 --send
```

- **Padrão seguro:** sem `--send` nada sai da máquina. Com `--send` pede para digitar `enviar` (ou `--yes`).
- **Só prompts e chamadas de ferramenta.** Respostas do modelo (`--include-responses`) e resultados de ferramenta (`--include-tool-results`: conteúdo de arquivos e saída de comandos, o mais sensível) são opt-in. O raciocínio interno do modelo nunca é enviado.
- **Idempotente:** o `event_id` usa a mesma fórmula do hook ao vivo (sessão, evento, `promptId` ou `tool_use_id`), então rodar de novo não duplica e, se o hook ao vivo já enviou o mesmo prompt, a API trata como duplicado. A coincidência com o hook ao vivo depende de o `prompt_id` do hook ser igual ao `promptId` da transcrição: **A VERIFICAR**.
- **Identificação:** `app=claude_code_import`, `integration_status=experimental`, `occurred_at` do registro original.
- **Ritmo:** 5 eventos por segundo por padrão (a API limita 600 por minuto por usuário); espera e tenta de novo no 429.
- **Efeito no servidor:** os eventos antigos passam pelas políticas atuais e **podem abrir incidentes e disparar alertas** (webhook, Slack, e-mail) sobre fatos passados. Importe em tenant de teste, sem canais de alerta ligados.
- A transcrição não é cifrada e já contém o que as ferramentas leram (inclusive `.env`); ela não passa por mascaração local antes do envio, quem mascara é a API.

## Testes

```bash
make test        # unitários do adaptador e o ponta a ponta (apps/api/tests/test_claude_hook_e2e.py, com PostgreSQL)
```
