# Guia simples: um servidor (hive) e um sensor em cada máquina

Dois passos. Status: **EXPERIMENTAL**. O servidor foi usado numa VM de teste; o sensor foi testado de ponta a ponta no Linux (instalador, hook e remoção) e **não** foi testado em Windows real, em MDM nem com as ferramentas reais do Copilot.

## Passo 1: o servidor (uma vez, em uma VM)

```bash
git clone https://github.com/rikosoo/AgenticIASec.git && cd AgenticIASec
git checkout claude/wonderful-hamilton-9dsk59
./infra/vm-setup.sh --admin-email voce@empresa.com
# opcional, para abrir o console e a API sem túnel (leia os avisos do script; limite as portas ao seu IP no firewall):
./infra/expose.sh --public-ip IP_DA_VM --web --api
```

Abra o console (`http://IP_DA_VM:3000`, ou `http://localhost:3000` pelo túnel), entre, vá em **Dispositivos**, crie um **token de matrícula** e copie a linha do seu sistema.

## Passo 2: o sensor (em cada máquina, uma linha)

Windows (PowerShell, sem administrador):

```powershell
$env:PS_API='http://IP_DA_VM:8000'; $env:PS_TOKEN='pse_...'; irm "$env:PS_API/sensor/install.ps1" | iex
```

Linux e macOS:

```bash
curl -fsSL http://IP_DA_VM:8000/sensor/install.sh | PS_API=http://IP_DA_VM:8000 PS_TOKEN=pse_... sh
```

O instalador: mostra o que será enviado e pede para digitar `sim`; baixa o sensor (um arquivo `.pyz`, só biblioteca padrão) e confere o SHA-256; troca o token por uma **chave própria desta máquina**; vincula o Claude Code e o GitHub Copilot CLI no usuário (sem administrador); **Opcional:** com `PS_TOOLS=claude_code,github_copilot_cli,browser_extension` também prepara a extensão do navegador (ChatGPT e Claude no site) numa pasta já configurada com a chave desta máquina. O navegador não deixa instalar extensão sozinho: falta UM passo seu, uma vez: em `chrome://extensions` (ou `edge://extensions`) ligar o Modo do desenvolvedor, clicar em **Carregar sem compactação** e escolher `~/.promptshield/extension` (no Windows, `%USERPROFILE%\.promptshield\extension`). A máquina aparece em **Dispositivos**, com as ferramentas vigiadas. Revogar uma máquina é um clique.

Para remover: `python3 ~/.promptshield/sensor/promptshield-sensor.pyz deploy --user --uninstall --confirm-employees-notified` (no Windows, `python` e `%USERPROFILE%\.promptshield\sensor\...`).

O instalador **pergunta quais IAs monitorar** (números separados por vírgula: 1 ChatGPT web, 2 Copilot web, 3 Gemini web, 4 Codex desktop, 5 Claude desktop, 6 Claude Code CLI, 7 Codex CLI, 8 Copilot desktop; 9 GitHub Copilot CLI e 10 Claude web foram acrescentados) e mostra o passo a passo de cada uma. Detalhes e o estado honesto de cada opção: `docs/guia-ias.md`.

## O que ainda NÃO é simples (e por quê)

| Limite | Estado |
|---|---|
| Precisa de Python 3.9+ na máquina | executável único assinado está decidido, não construído |
| O script e o sensor baixados por HTTP podem ser trocados por quem estiver no caminho | em produção, HTTPS é obrigatório; o instalador confere um SHA-256 que vem do mesmo servidor (protege de download corrompido, não de ataque no caminho) |
| A extensão do navegador precisa de um clique seu (Carregar sem compactação) e os seletores de ChatGPT e Claude **nunca foram conferidos nos sites reais** | instalação forçada por política do Chrome/Edge: não construída; testada só em página simulada com os seletores do ChatGPT |
| Não cobre o chat do app Claude Desktop, nem o Copilot do VS Code, nem Codex | sem hooks documentados / a verificar |
| Instalação em nível de máquina (todos os usuários, por MDM) | existe como `deploy` sem `--user`, nunca testado em MDM real |
| Login do console em modo de teste (mock) | login real (OIDC) nunca testado com provedor real |

## Ver os sensores instalados e as IAs de cada um (painel **Sensores**)

No console, **Sensores** mostra todas as máquinas com sensor, pelo **nome da máquina** (hostname), com o sistema, a versão do sensor, o último envio e **as IAs habilitadas em cada uma** (as que a pessoa escolheu por número na instalação ou no assistente `setup`). Filtros: nome da máquina, IA e situação. Clicar na máquina mostra, por IA, como ela é monitorada e quantos eventos chegaram em 7 e 30 dias.

Como ler:
- **capturando**: chegou evento dessa IA nos últimos 7 dias (prova real, não suposição).
- **aguardando evento**: a IA foi habilitada mas ainda não chegou nada. Para IAs de navegador isso pode ser só o clique que falta para carregar a extensão.
- **sem eventos há 7 dias+**: já chegou antes e parou.
- **manual** / **indisponível hoje**: o sensor não configura sozinho ou não há como monitorar; nunca aparece como "capturando".
- O sensor só fala com o servidor quando alguém usa uma IA. **"Sem atividade" não quer dizer que o sensor quebrou.**
- "Não informado": sensor instalado antes desta versão, ou com `--tools` em vez de `--ias`. Reinstale com `--ias` ou rode `setup` e escolha as IAs.

Mais no painel **Sensores**:
- **Último usuário** de cada máquina (calculado dos eventos dos últimos 30 dias) e quantas pessoas diferentes a usaram; mais de uma sugere máquina compartilhada.
- **Alertas** (pistas, não provas): *nunca enviou* (matriculada há mais de 24 h), *sem atividade há mais de 7 dias*, *extensão sem nenhum evento* (IA de navegador habilitada há mais de 3 dias e nenhum evento em 30 dias: provavelmente falta carregar a extensão ou o site mudou) e *sensor desatualizado* (versão atrás da mais nova da frota). Clicar no alerta filtra a tabela.
- **Ver os prompts deste sensor**: abre **Todos os prompts** só com os eventos enviados por aquela máquina.
- **Exportar CSV** (administrador e auditor; fica na auditoria): colunas `maquina, sistema, versao_sensor, situacao, matriculada_em, ultimo_envio, ultimo_usuario, usuarios_30d, ias_habilitadas, ias_capturando_7d, mecanismos, ocupa_vaga`, respeitando os filtros da tela (nome, IA e situação). O filtro de alerta é só da tela.
- Eventos anteriores à versão que passou a guardar o sensor de origem não entram em "último usuário" nem nas contagens por IA.

