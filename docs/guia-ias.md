# Escolher quais IAs monitorar (com passo a passo de cada uma)

Estado em 2026-11-05. **Testado** quer dizer: o dono viu a captura funcionar numa máquina real. Não é garantia de que continua funcionando (sites mudam o HTML). Tudo o que não diz "testado" é **experimental**.

Os apps de desktop (Codex, Claude e Copilot) **não são cobertos** e saíram da lista: não há gancho documentado que o sensor possa usar sem agente de desktop ou proxy, que estão fora do escopo do projeto.

## Como escolher

No instalador de uma linha (ele pergunta) ou no assistente (`python -m promptshield_claude_hook setup`, opção 8), digite os números separados por vírgula, por exemplo `1,3,5`, ou `todas`. Sem uma resposta, o padrão é o Claude Code e o GitHub Copilot CLI (e o Codex CLI, se estiver instalado nesta máquina).

| N | IA | Estado | O que acontece |
|---|---|---|---|
| 1 | ChatGPT (web, chatgpt.com) | extensão, **testado** | o sensor prepara a extensão; você carrega a pasta no navegador uma vez. Prompts reais apareceram no console (2026-11-04); os seletores dependem do HTML do site |
| 2 | Copilot (web, copilot.com) | extensão, experimental | idem; campo e botão conferidos no HTML real, falta teste de ponta a ponta. Não cobre o GitHub Copilot em github.com/copilot nem o Microsoft 365 Copilot |
| 3 | Gemini (web, gemini.google.com) | extensão, **testado** | idem 1. Prompts reais apareceram no console (2026-11-04) |
| 4 | Claude (web, claude.ai) | extensão, experimental | idem; seletores nunca conferidos na página real |
| 5 | Claude Code (CLI) | automático, **testado** | hooks no `~/.claude/settings.json`, com cópia de segurança |
| 6 | Codex (CLI) | automático, experimental | grava hooks em `~/.codex/hooks.json`; o Codex exige que você confie neles em `/hooks`. No primeiro teste real o hook falhou com código 1; corrigido, ainda não visto enviando (ver abaixo) |
| 7 | GitHub Copilot CLI | automático, experimental | arquivo `~/.copilot/hooks/promptshield.json`; o prompt só é monitorado |

## Passo a passo

**Extensão do navegador (1, 2, 3, 4).** Uma extensão só cobre os quatro sites.
1. O sensor a prepara em `~/.promptshield/extension` (Windows: `%USERPROFILE%\.promptshield\extension`), já com a chave da máquina.
2. No navegador abra `chrome://extensions` (Edge: `edge://extensions`) e ligue o **Modo do desenvolvedor**.
3. **Carregar sem compactação** e escolha a pasta. Só na primeira vez.
4. Abra o site e recarregue: deve aparecer "PromptShield: monitoramento ativo". Se o aviso disser que o monitoramento pode estar inativo, o site mudou o HTML e o seletor precisa de ajuste.
5. Para empresa: instalação forçada por política do navegador, sem clique (não construída, A VERIFICAR).

**Claude Code CLI (5).**
1. O sensor grava os hooks no `settings.json` do usuário. Feche e abra de novo as sessões do Claude Code.
2. Teste com `SIMULADO: o CPF de teste é 529.982.247-25` e veja o evento em **Análise de prompts**.

**Codex CLI (6), automático (experimental).** O instalador acrescenta os hooks ao `~/.codex/hooks.json` sem tocar nos seus. Abra o Codex CLI e digite `/hooks` para confiar neles (sem isso o Codex os ignora). **Reinstalou ou atualizou o sensor? O comando do hook mudou: confie de novo em `/hooks`.** Teste com um prompt sintético; os eventos aparecem como `codex_cli`. O nome do campo do prompt está A VERIFICAR contra o Codex real: o hook aceita vários nomes e, se não achar o texto, registra no log só os **nomes** dos campos que chegaram.

**GitHub Copilot CLI (7).** Abra uma nova sessão e mande um prompt sintético. Não cobre o Copilot dentro do VS Code.

## Quando o CLI mostra "Hook failed" ou nada aparece no console

Rode no computador onde o CLI está:

```text
python <sensor.pyz> doctor
```

(o `.pyz` fica em `~/.promptshield/sensor/promptshield-sensor.pyz`; no assistente, opção 9.) O `doctor` pega o comando de cada hook **exatamente como está gravado**, roda no shell da máquina (no Windows, `cmd` e PowerShell) com um texto sintético e mostra o código de saída e o erro. Também mostra as últimas linhas de `~/.promptshield/hook.log`, o registro de falhas dos hooks: horário, IA, evento, tipo do erro e **nomes** dos campos recebidos, nunca o texto do prompt.

Desde 2026-11-05 o hook **nunca sai com código diferente de 0 por defeito nosso** (lê a entrada em UTF-8 e escreve só ASCII), e o comando gravado para o Codex não começa com texto entre aspas, que o PowerShell trata como erro de sintaxe. A causa exata do "código 1" no primeiro teste real **não foi confirmada** (a documentação oficial de hooks do Codex não pôde ser lida neste ambiente): o `doctor` e o log existem para mostrá-la.

## Remover
`python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified` (opção 7 do assistente), e revogue a máquina em **Dispositivos**.
