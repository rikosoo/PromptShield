# Teste com o servidor em uma VM e o coletor no seu computador

Cenário: API, banco e console em uma VM Linux com Docker (qualquer nuvem; este guia não depende de produto de nuvem), e o hook do Claude Code rodando no seu Windows, enviando para a VM. **Não executado ainda.** É um ambiente de teste, não uma decisão de produção (a nuvem de produção continua indefinida).

## Avisos antes de começar (são dados reais seus)

Com o hook ligado, o que você digita no Claude Code e as ações dele passam a ser enviados e guardados. Isso foge da regra de só usar dados sintéticos nos testes, então:

- Só o seu uso, por sua decisão, em um tenant de teste. Nada de terceiros.
- Mantenha tudo em **modo monitorar** (padrão). Não crie política de bloqueio com dados reais sem querer.
- Deixe desligado o armazenamento de texto original (padrão). O texto é guardado mascarado e a categoria saúde nem guarda texto.
- A mascaração é heurística e erra (ver `docs/deteccao.md`: cerca de 82% de acerto em conjunto sintético independente). **Trate o banco da VM como se contivesse segredos seus**: não coloque chave, senha ou dado de cliente em prompts durante o teste.
- Defina a retenção curta (padrão 90 dias; para o teste, apague o volume ao terminar: `docker compose down -v`).

## Regra de ouro de exposição

`OIDC_MODE=mock` habilita `POST /dev/token`, que **emite token para qualquer e-mail**. Em máquina acessível pela internet isso é uma porta aberta. Por isso:

1. **Não abra as portas 8000, 3000 e 5432 para a internet.** No firewall da VM (grupo de segurança), deixe só a porta 22 (SSH), restrita ao seu IP.
2. Acesse tudo por túnel SSH. Sem domínio, sem certificado, sem exposição.

## Passos

Na VM (Debian ou Ubuntu, com Git; o script instala o Docker se faltar):

```bash
git clone https://github.com/rikosoo/PromptShield.git && cd PromptShield
git checkout claude/nifty-hopper-y3ddn0
./infra/vm-setup.sh --admin-email voce@exemplo.com
```

O script (`infra/vm-setup.sh`, **não executado em máquina real**) cria o `.env` com segredos aleatórios e login `mock`, sobe tudo com as portas em `127.0.0.1`, espera a API ficar saudável e cria o tenant. **Guarde a chave `ps_...`** (aparece uma vez). Ele recusa subir se o `.env` tiver `BIND_ADDR` diferente de loopback. Sem `seed-demo`: você quer ver só os seus eventos.

As portas do `docker-compose.yml` escutam só em `127.0.0.1` por padrão (variável `BIND_ADDR`). O firewall do passo 1 continua sendo a primeira barreira.

No seu Windows (PowerShell), abra o túnel e deixe a janela aberta:

```powershell
ssh -N -L 8000:localhost:8000 -L 3000:localhost:3000 usuario@IP_DA_VM
```

Depois siga `docs/teste-windows.md`, passo 1, com `api_url` = `http://localhost:8000` (que agora cai na VM pelo túnel) e o console em <http://localhost:3000>. O tráfego vai cifrado pelo SSH; o `http://` local é só até o túnel.

Se o túnel cair, o hook segue em `fail_mode: open` (grava só metadados localmente), então o Claude Code não trava.

## Sem túnel (opcional, menos seguro)

Se você preferir acessar por `http://IP_PUBLICO:3000`, limite as portas ao SEU IP no firewall da nuvem e rode na VM:

```bash
git pull origin claude/nifty-hopper-y3ddn0
./infra/expose.sh --public-ip IP_PUBLICO --web            # só o console (porta 3000)
./infra/expose.sh --public-ip IP_PUBLICO --web --api      # também a API (porta 8000)
./infra/expose.sh --close                                 # volta ao modo seguro (só túnel)
```

Riscos que o script repete e exige confirmar: o login é **mock** (quem alcançar a porta entra com um e-mail cadastrado) e o tráfego é **HTTP sem cifra**. O console mostra só texto mascarado, mas o **hook envia o texto original** à API: expor a API em HTTP faz esse texto cruzar a internet sem cifra. O banco nunca é exposto. O IP público muda se a instância for parada e religada (use um Elastic IP) e o seu IP residencial também pode mudar. A solução definitiva é domínio + HTTPS + login real (`docs/roteiro-testes-reais.md`, passo 2).

## Mudar para portas altas (opcional)

Por padrão o console usa a porta **3000** e a API a **8000**. Para trocar, edite o `.env` da VM **antes** de abrir:

```bash
# .env
WEB_PORT=13000
API_PORT=18000
```

Regras: números de 1024 a 65535, diferentes entre si. Prefira **abaixo de 32768**: o Linux usa 32768 a 60999 para conexões de saída e pode colidir. Depois:

```bash
./infra/expose.sh --public-ip IP_PUBLICO --web --api    # grava PUBLIC_BASE_URL com a porta nova e mostra quais portas liberar
```

E no firewall da nuvem (grupo de segurança): **troque** as regras antigas pelas novas (TCP 13000 e 18000), sempre **só para o seu IP**.

O que muda por causa da porta:
- O console passa a ser `http://IP:13000` e a API `http://IP:18000`.
- **Os sensores já instalados guardam o endereço antigo** (`api_url` em `~/.promptshield/hook.json` e na pasta da extensão). Reinstale com `PS_API='http://IP:18000'` e um token novo, ou edite o `api_url`. Até lá, eles seguem em falha aberta (sem monitorar), e o painel mostra "sem atividade".
- O campo "Endereço público da API" da página Dispositivos (que monta a linha de instalação) precisa da porta nova.

**Porta alta não é segurança.** Ela só reduz o barulho de varredura automática; quem varre a faixa inteira acha de qualquer jeito. O que protege é a regra do firewall limitada ao seu IP, e depois HTTPS e login de verdade. Para **clientes**, o certo é o contrário: **443 com HTTPS e domínio**, porque redes de empresa costumam deixar sair só 80 e 443, e uma porta incomum pode ser bloqueada no firewall ou no proxy deles.

Para conferir o que está aberto: na VM, `docker compose ps` mostra `0.0.0.0:18000->8000` (aberta) ou `127.0.0.1:...` (só local); no seu Windows, `Test-NetConnection IP_PUBLICO -Port 18000`. O banco (5432) nunca é aberto.

## Histórico que já existe na sua máquina

Além do uso ao vivo, dá para importar as transcrições locais (últimos 30 dias, se você não mudou `cleanupPeriodDays`). Primeiro simule, depois envie, ainda com o túnel aberto e em tenant sem canais de alerta:

```powershell
$env:PROMPTSHIELD_HOOK_CONFIG = "C:\ps-teste\hook.json"
python -m promptshield_claude_hook import --preview 5
python -m promptshield_claude_hook import --send
```

Detalhes e opt-ins (respostas, resultados de ferramenta) em `packages/adapters/claude_code_hook/README.md`. As transcrições contêm tudo que o Claude Code leu, inclusive arquivos `.env`: o que a API não reconhecer como segredo fica no banco da VM.

## Ao terminar

```bash
docker compose down -v      # apaga banco e eventos
```

Apague também `C:\ps-teste\hook.json` (tem a chave) e revogue a chave no console.

## Limites deste arranjo

Não valida TLS com domínio, nem OIDC com provedor real, nem o que um colaborador de outra máquina faria. Serve para ver o fluxo real de ponta a ponta com o seu uso.
