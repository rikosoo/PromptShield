# Hooks do Claude Code: o que a documentação confirma (Etapa 4)

Lido em **2026-10-14** nas páginas oficiais abaixo. Onde a página não confirma, está marcado **A VERIFICAR**. Nada aqui foi testado dentro de uma sessão real do Claude Code: o adaptador foi testado com as entradas JSON simuladas segundo estes formatos (ver "Estado da integração").

Fontes:
- [Hooks reference](https://code.claude.com/docs/en/hooks) (268 mil caracteres; li todas as seções citadas aqui)
- [Deploy managed settings](https://code.claude.com/docs/en/managed-settings)
- [Monitoramento (OpenTelemetry)](https://code.claude.com/docs/en/monitoring-usage)

## Eventos que usamos

| Evento | Quando dispara | Usamos para |
|---|---|---|
| `UserPromptSubmit` | quando o usuário envia um prompt (também em tarefas agendadas, `/loop`, relatórios de subagentes em segundo plano e mensagens de outras sessões) | `kind: prompt` |
| `PreToolUse` | antes de cada ferramenta rodar | `kind: tool_call` |
| `PostToolUse` | depois da ferramenta rodar | `kind: tool_result` (injection indireta em arquivo, página ou resultado de MCP) |

Existem muitos outros eventos (`SessionStart`, `Stop`, `PermissionRequest`, `SubagentStart`...). Não usamos.

## Entrada (stdin, JSON)

Campos comuns: `session_id`, `prompt_id` (UUID do prompt em processamento), `transcript_path`, `cwd`, `permission_mode`, `effort`, `hook_event_name`, e `agent_id`/`agent_type` em subagentes.

- `UserPromptSubmit` acrescenta `prompt` (texto colado chega expandido e pode vir entre linhas `<pasted_content id="…">`) e, às vezes, `session_title`.
- `PreToolUse` acrescenta `tool_name`, `tool_input` (para Bash: `command`, `description`, `timeout`, `run_in_background`) e `tool_use_id`.
- `PostToolUse` acrescenta `tool_name`, `tool_input`, `tool_response` (objeto cujo formato depende da ferramenta; para MCP vem também `mcp_server`), `tool_use_id` e, opcionalmente, `duration_ms`.

**O JSON de entrada não traz identidade do usuário** (e-mail, conta). Nem se a conta é pessoal ou corporativa. **A VERIFICAR** se alguma versão passa isso. O adaptador usa usuário e hostname do sistema operacional, ou valores da configuração do administrador.

## Saída

Exit code `0` com JSON único em stdout é interpretado. Exit `2` bloqueia nos eventos que bloqueiam (stderr é o motivo). **Exit `1` e qualquer outro código não bloqueiam** (erro não bloqueante).

| Evento | Como bloquear | Observações |
|---|---|---|
| `UserPromptSubmit` | `{"decision": "block", "reason": "…"}` | `reason` é mostrado ao usuário, não ao Claude. **Não dá para reescrever o prompt**; só injetar `additionalContext` (até 10.000 caracteres). |
| `PreToolUse` | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "…"}}` | Valores: `allow`, `deny`, `ask`, `defer`. Precedência entre hooks: `deny` > `defer` > `ask` > `allow`. `defer` só vale com `-p` e uma única chamada. `updatedInput` substitui o objeto de entrada inteiro. |
| `PostToolUse` | `{"decision": "block", "reason": "…"}` | A ferramenta já rodou. `updatedToolOutput` substitui o resultado, mas o valor precisa ter o formato da ferramenta. |

Campos universais: `continue`, `stopReason`, `suppressOutput`, `systemMessage`.

## Tipos de hook, falha e timeout

- Tipos: `command`, `http`, `mcp_tool`, `prompt`, `agent`.
- **`http`**: POST do JSON de entrada com `Content-Type: application/json`; campos `url`, `headers` (com `$VAR` só para variáveis listadas em `allowedEnvVars`). Resposta 2xx com corpo JSON é interpretada como a saída do `command`; **status não 2xx, falha de conexão e timeout são erros que NÃO bloqueiam**. Para bloquear nesses casos é preciso `onFailure: "block"` (exige Claude Code **2.1.295 ou mais novo**).
- **`command`**: campos `command`, `args` (forma exec, sem shell, "Set `args` whenever the hook references a path placeholder"), `shell`, `async`, `onFailure`.
- `timeout` (segundos): padrão 600 em `command`/`http`/`mcp_tool`; **30 em `UserPromptSubmit`**; 10 em `MessageDisplay`. Timeout em `PreToolUse` não bloqueia a chamada, salvo `onFailure: "block"`.

**Consequência para o desenho:** o adaptador é um `command` em forma exec que decide sozinho entre fail-open e fail-closed (RNF03) e responde sempre com JSON válido. Um hook `http` direto para a API deixaria o Claude Code seguir sem inspeção sempre que a API caísse.

## Configuração gerenciada

- Arquivo `managed-settings.json` (e/ou `managed-settings.d/*.json`):
  - macOS: `/Library/Application Support/ClaudeCode/managed-settings.json`
  - Linux e WSL: `/etc/claude-code/managed-settings.json`
  - Windows: `C:\Program Files\ClaudeCode\managed-settings.json` (o caminho antigo `C:\ProgramData\ClaudeCode\` **não** é lido)
- Outros mecanismos: perfil de configuração no macOS (domínio `com.anthropic.claudecode`), registro `HKLM\SOFTWARE\Policies\ClaudeCode` (valor `Settings`, JSON), configurações gerenciadas pelo servidor (console do claude.ai). Se mais de um mecanismo entrega política, por padrão o Claude Code usa um e ignora os outros (ordem na página).
- Estrutura: `hooks` → evento → lista de `{matcher, hooks: [{type, command, args, timeout, onFailure}]}`.
- `allowManagedHooksOnly: true` bloqueia hooks de usuário, projeto e plugins. É opcional: é uma imposição forte sobre os clientes, então o instalador **não** liga por padrão.
- `disableAllHooks` fora da configuração gerenciada não desliga hooks gerenciados.
- Um usuário com direito de administrador na máquina pode editar a própria fonte gerenciada; por isso o produto não deve ser apresentado como controle contra o próprio dono da máquina.

## Estado da integração (classificação)

**REAL, com limites do que foi testado.** Em 2026-10-14, com o **Claude Code 2.1.296** (`claude -p`, modo não interativo), carregando as configurações por `--settings`:

- `UserPromptSubmit`: um prompt com chave AWS sintética foi **bloqueado pelo hook** antes de qualquer chamada ao modelo (custo zero). O Claude Code respondeu `UserPromptSubmit operation blocked by hook:` seguido da nossa mensagem.
- `PreToolUse`: o comando `cat ~/.aws/credentials`, pedido ao modelo, foi **negado** (`permission_denials` com a chamada Bash; o modelo relatou o bloqueio e não tentou contornar).
- A API recebeu e gravou os eventos, com a decisão `block`.

**O que NÃO foi testado no Claude Code real:** `PostToolUse` (só com entradas simuladas), `permissionDecision: "ask"`, sessão interativa, entrega por `managed-settings.json` ou MDM (foi por `--settings`, para não alterar a política desta sessão), Windows, e `onFailure: "block"`. Esses itens seguem **PARCIAL**: formato documentado e testado só com entradas simuladas (`apps/api/tests/test_claude_hook_e2e.py`).

Observação: ao bloquear um prompt, o próprio Claude Code reexibe o prompt original no resultado do modo `-p` ("Original prompt: …"). É comportamento do Claude Code, local ao usuário; o PromptShield não envia isso a lugar nenhum.

## Decisões de mapeamento (decisão da política → resposta ao Claude Code)

| Decisão da API | `UserPromptSubmit` | `PreToolUse` | `PostToolUse` |
|---|---|---|---|
| `allow`, `alert` | segue (alerta só vai para o console) | segue | segue |
| `block` | `decision: block` | `permissionDecision: deny` | `decision: block` |
| `mask` | `decision: block` com a versão mascarada na mensagem (o prompt não pode ser reescrito) | `permissionDecision: ask` | segue |
| `ask_justification` | `decision: block` pedindo para reenviar com justificativa **(justificativa em linha ainda não existe)** | `permissionDecision: ask` | segue |

Em modo monitorar a API devolve sempre `allow`; o adaptador nunca bloqueia nem pergunta nada.
