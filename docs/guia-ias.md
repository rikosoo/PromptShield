# Escolher quais IAs monitorar (com passo a passo de cada uma)

Estado em 2026-10-17. Tudo aqui é **EXPERIMENTAL ou PARCIAL**: nada foi validado em máquina de cliente.

## Como escolher

No instalador de uma linha (ele pergunta) ou no assistente (`python -m promptshield_claude_hook setup`, opção 8), digite os números separados por vírgula, por exemplo `1,2,6`, ou `todas`. Sem uma resposta, o padrão é o Claude Code e o GitHub Copilot CLI. Para pular a pergunta: `PS_IAS=1,6` antes do comando, ou `deploy --ias 1,6`. A lista com o estado de cada uma: `python <sensor.pyz> deploy --list-ias --confirm-employees-notified`.

| N | IA | Estado | O que acontece |
|---|---|---|---|
| 1 | ChatGPT (web, chatgpt.com) | extensão, experimental | o sensor prepara a extensão; você carrega a pasta no navegador uma vez |
| 2 | Copilot (web, copilot.com) | extensão, experimental | idem; seletores nunca conferidos na página real. Não cobre o GitHub Copilot em github.com/copilot nem o Microsoft 365 Copilot |
| 3 | Gemini (web, gemini.google.com) | extensão, experimental | idem; seletores nunca conferidos na página real |
| 4 | Codex (app desktop) | indisponível hoje | sem hooks documentados para o app desktop nas fontes lidas: A VERIFICAR |
| 5 | Claude (app desktop) | manual | a aba Code usa os mesmos arquivos de configuração do CLI (marque também o 6; o disparo dos hooks lá é A VERIFICAR). O chat comum não tem hooks e não é coberto |
| 6 | Claude Code (CLI) | automático | hooks no `~/.claude/settings.json`, com cópia de segurança |
| 7 | Codex (CLI) | automático, experimental | grava hooks em ~/.codex/hooks.json (formato da documentação de Hooks do Codex, cópia colada em 2026-11-04); o Codex exige que você confie nos hooks em /hooks; nunca rodou no Codex real |
| 8 | Copilot (app desktop) | indisponível hoje | Microsoft 365 Copilot só por API do servidor (Graph; conector não construído); o Copilot gratuito do Windows não tem gancho |
| 9 | GitHub Copilot CLI | automático, experimental | arquivo `~/.copilot/hooks/promptshield.json`; o prompt só é monitorado |
| 10 | Claude (web, claude.ai) | extensão, experimental | idem 1 |

## Passo a passo

**Extensão do navegador (1, 2, 3, 10).** Uma extensão só cobre os quatro sites.
1. O sensor a prepara em `~/.promptshield/extension` (Windows: `%USERPROFILE%\.promptshield\extension`), já com a chave da máquina.
2. No navegador abra `chrome://extensions` (Edge: `edge://extensions`) e ligue o **Modo do desenvolvedor**.
3. **Carregar sem compactação** e escolha a pasta. Só na primeira vez.
4. Abra o site e recarregue: deve aparecer "PromptShield: monitoramento ativo". Se o aviso disser que o monitoramento pode estar inativo, o site mudou o HTML e o seletor precisa de ajuste.
5. Para empresa: instalação forçada por política do navegador, sem clique (não construída, A VERIFICAR).

**Claude Code CLI (6) e app Claude Desktop, aba Code (5).**
1. O sensor grava os hooks no `settings.json` do usuário. Feche e abra de novo as sessões do Claude Code.
2. Teste com `SIMULADO: o CPF de teste é 529.982.247-25` e veja o evento em **Análise de prompts**.
3. No app desktop, teste também na aba Code. O chat comum e o Cowork não passam por hooks.

**Codex CLI (7), automático (experimental).** O instalador acrescenta os hooks ao ~/.codex/hooks.json sem tocar nos seus. Abra o Codex CLI e digite /hooks para confiar neles (sem isso o Codex os ignora). Teste com um prompt sintético; os eventos aparecem como codex_cli. O nome do campo do prompt no UserPromptSubmit está A VERIFICAR contra o Codex real.

**Codex desktop (4) e Copilot desktop (8).** Sem integração possível hoje. O 8 tem um caminho de servidor (Microsoft Graph) que depende de um tenant com licença do Microsoft 365 Copilot e do consentimento do administrador.

**GitHub Copilot CLI (9).** Abra uma nova sessão e mande um prompt sintético. Não cobre o Copilot dentro do VS Code.

## Remover
`python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified` (opção 7 do assistente), e revogue a máquina em **Dispositivos**.
