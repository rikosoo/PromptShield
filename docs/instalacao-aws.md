# Instalar o PromptShield em um servidor na AWS (EC2), passo a passo

**Para quê serve:** um servidor de **teste** seu, numa máquina virtual (EC2) com Docker. É o mesmo arranjo de `docs/teste-vm.md`, com os cliques da AWS. **Não é a arquitetura de produção**: a nuvem de produção continua indefinida (nada aqui usa RDS, ECS, S3 ou outro serviço gerenciado; o produto roda igual em qualquer VM Linux).

**Tempo:** cerca de 30 minutos. **Custo:** o de uma instância EC2 e do disco enquanto existirem; confira o preço atual na página de preços da AWS e **pare ou apague tudo ao terminar** (passo 11).

> As telas do console da AWS mudam de lugar e de nome. Se algo não estiver onde o guia diz, procure pelo nome em negrito.

## Antes de começar: o que você precisa saber

- Este servidor sobe com login **mock** (`OIDC_MODE=mock`): quem alcançar a API emite token para qualquer e-mail. Por isso o guia deixa **tudo fechado**, só SSH liberado para o seu IP, e você acessa por túnel. Não abra portas para a internet sem ler `docs/teste-vm.md` ("Regra de ouro de exposição").
- **HTTPS e domínio ainda não existem** no produto. Com túnel SSH o tráfego vai cifrado até a VM; para colocar **outras pessoas** (funcionários) no sistema, falta HTTPS, login real (OIDC) e domínio: veja `docs/dominio-e-assinatura.md` e `docs/roteiro-testes-reais.md`. Este guia valida o fluxo com **o seu uso**.
- O hook do Claude Code envia o **texto original** à API; só o console mostra texto mascarado. Use dados **sintéticos** ou o seu uso por sua decisão, em modo **monitorar** (padrão). Não escreva chave, senha ou dado de cliente nos prompts do teste.

> **Estado honesto:** o cabeçalho de `infra/vm-setup.sh` ainda diz "não executado em máquina real", embora o README registre um servidor de teste na AWS visto rodando. Este guia foi escrito a partir dos scripts e dos documentos do repositório, **não** executado por mim numa conta AWS: se algum passo falhar, anote o erro e a tela, porque é assim que ele se corrige.

## 1. Conta e região

1. Entre no console da AWS com uma conta sua. Não use a conta root para o dia a dia (crie um usuário do IAM com permissão para EC2).
2. No canto superior direito, escolha a **região**. Para dados de pessoas no Brasil, **São Paulo (sa-east-1)** costuma ser a escolha; o que vale é decidir de propósito, porque dados pessoais ficarão nessa região (veja `docs/lgpd.md`, transferência internacional).

## 2. Par de chaves (para entrar por SSH)

1. **EC2 → Network & Security → Key pairs → Create key pair**.
2. Nome: `promptshield-teste`. Tipo **ED25519**, formato **.pem**.
3. O navegador baixa o arquivo `.pem`. **Guarde-o**: a AWS não o mostra de novo.
   - Linux/macOS: `chmod 400 promptshield-teste.pem`
   - Windows: guarde numa pasta sua; no PowerShell o `ssh` do Windows 10/11 aceita `-i caminho\promptshield-teste.pem`.

## 3. Grupo de segurança (o firewall)

1. **EC2 → Network & Security → Security groups → Create security group**.
2. Nome: `promptshield-teste`. VPC: a padrão.
3. **Inbound rules** (entrada), **uma só regra**: tipo **SSH**, porta 22, origem **My IP** (o console preenche o seu IP atual).
4. Não adicione 3000, 8000 nem 5432. **Outbound** (saída): deixe o padrão (a VM precisa baixar Docker e imagens).

> Seu IP residencial pode mudar. Se o SSH parar de entrar, volte aqui e atualize a origem.

## 4. Criar a instância

**EC2 → Instances → Launch instances**:

| Campo | Valor |
|---|---|
| Nome | `promptshield-teste` |
| Imagem (AMI) | **Ubuntu Server 24.04 LTS** (o script usa `apt`; funciona em Debian/Ubuntu) |
| Tipo | **4 GB de memória ou mais** (por exemplo `t3.medium`). Com 2 GB o build funciona (o `atualizar.sh` constrói um serviço por vez de propósito), mas fica no limite |
| Par de chaves | `promptshield-teste` |
| Rede | grupo de segurança existente: `promptshield-teste`; **Auto-assign public IP: Enable** |
| Armazenamento | **20 GB gp3** ou mais (imagens Docker e banco crescem) |

Clique em **Launch instance**. Quando o estado for **Running**, copie o **IP público IPv4** (aba de detalhes).

> O IP público muda se você parar e religar a instância. Para um IP fixo, associe um **Elastic IP** (EC2 → Elastic IPs); ele cobra enquanto não estiver em uso.

## 5. Entrar na máquina

No seu computador:

```bash
ssh -i promptshield-teste.pem ubuntu@IP_PUBLICO
```

Se aparecer a pergunta sobre a impressão digital da chave, responda `yes`. O usuário padrão do Ubuntu na AWS é `ubuntu`.

## 6. Baixar o código

Dentro da VM:

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/rikosoo/PromptShield.git && cd PromptShield
git checkout claude/nifty-hopper-y3ddn0
```

- Se o repositório for **privado**, o `git clone` pede usuário e senha: use seu usuário do GitHub e, como senha, um **token de acesso pessoal** do GitHub com permissão **somente de leitura** do conteúdo deste repositório. Não grave o token em arquivo nem em script.
- A branch `claude/nifty-hopper-y3ddn0` é a atual. Quando ela for incorporada à principal, troque pelo nome da principal.

## 7. Instalar e subir

```bash
./infra/vm-setup.sh --admin-email voce@exemplo.com
```

O script instala o Docker (se faltar), cria o `.env` com segredos aleatórios e login `mock`, sobe banco, API, worker e console **só em `127.0.0.1`**, espera a API ficar saudável e cria o tenant. Isso leva alguns minutos no primeiro build.

- **Copie a chave `ps_...`** que aparece no fim: ela não é mostrada de novo.
- Se der "permission denied" no Docker, o script já tenta com `sudo`. Para usar sem `sudo` depois: `sudo usermod -aG docker $USER` e entre de novo no SSH.
- Conferir: `docker compose ps` deve mostrar os serviços `Up` com portas `127.0.0.1:...` (nada em `0.0.0.0`).
- Se a API não ficar saudável: `docker compose logs api | tail -50`. Falta de memória aparece como processo morto (`Killed`) no build: use uma instância maior.

## 8. Abrir o console por túnel SSH

No **seu computador**, em outro terminal, deixe aberto:

```bash
ssh -i promptshield-teste.pem -N -L 3000:localhost:3000 -L 8000:localhost:8000 ubuntu@IP_PUBLICO
```

Abra <http://localhost:3000> e entre com o e-mail que você passou em `--admin-email` (no modo mock não há senha). O `http://` é só até o túnel; dali à VM vai cifrado pelo SSH.

## 9. Ligar o primeiro sensor (a sua máquina)

1. No console: **Dispositivos → Criar token** (nome, validade, número de usos). O token `pse_...` aparece uma vez.
2. No seu computador, com o túnel aberto, instale o sensor apontando para `http://localhost:8000`:
   - Windows (PowerShell): `$env:PS_API='http://localhost:8000'; $env:PS_TOKEN='pse_...'; irm "$env:PS_API/sensor/install.ps1" | iex`
   - Linux/macOS: `curl -fsSL http://localhost:8000/sensor/install.sh | PS_API=http://localhost:8000 PS_TOKEN=pse_... sh`
3. O instalador pergunta quais IAs monitorar (números de 1 a 7; estado de cada uma em `docs/guia-ias.md`). Para a extensão do navegador, carregue a pasta uma vez em `chrome://extensions`.
4. Teste com um prompt **sintético**, por exemplo `SIMULADO: o CPF de teste é 529.982.247-25`, e veja o evento em **Todos os prompts** e em **Sensores**.

Se o túnel cair, o sensor segue em "falha aberta" (não trava a ferramenta e não monitora até voltar).

## 10. Manter

- **Atualizar** (com backup antes): na VM, `bash infra/atualizar.sh`. Ele faz backup do banco em `~/backups`, baixa o código da branch atual, reconstrói e confere. **Nunca use `docker compose down -v`** em dados que quer manter.
- **Backup**: `infra/backup.sh` (URL do dono do banco). O backup **não inclui a chave mestra** (`ORIGINAL_TEXT_MASTER_KEY`): guarde-a à parte (`docs/operacao.md`).
- **Backup do `.env`**: ele tem as senhas; o `atualizar.sh` copia para `~/backups`. Esses arquivos ficam só na VM: baixe uma cópia para um lugar seu seguro, porque se a instância for apagada eles somem junto.

## 10b. Ligar o login com e-mail e senha (recomendado)

Até aqui o console entra só com o e-mail (modo de teste). Estes passos trocam isso por **e-mail e senha**, com troca obrigatória da senha provisória, bloqueio após 5 tentativas erradas (15 minutos) e sessões que caem quando a senha muda. Política de senha: 8 ou mais caracteres, com minúscula, maiúscula, número e caractere especial.

**A ordem importa: dê senha ao administrador ANTES de desligar o login só com e-mail, senão você fica trancado fora.**

1. Atualize para a versão com senha (cria colunas novas no banco; faz backup antes): `bash infra/atualizar.sh <branch>`.
2. Gere uma senha temporária para o seu administrador (o login antigo continua funcionando até o passo 4):
   ```bash
   sudo docker compose exec api python -m app.cli set-password --email SEU_EMAIL_DE_ADMIN --generate
   ```
   A senha temporária aparece **uma única vez**: anote.
3. Ligue o login com senha no `.env` e recrie os serviços:
   ```bash
   sed -i '/^LOCAL_AUTH=/d;/^LOCAL_AUTH_SECRET=/d' .env
   printf 'LOCAL_AUTH=true\nLOCAL_AUTH_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env
   sed -i 's/^AUTH_MODE=.*/AUTH_MODE=local/; s/^OIDC_MODE=.*/OIDC_MODE=off/' .env
   sudo docker compose up -d --force-recreate api web
   ```
   `OIDC_MODE=off` é essencial: com `mock` ligado, a rota `/dev/token` emite sessão para qualquer e-mail e **contorna a senha**.
4. Entre no console com o e-mail e a senha temporária; o sistema pede para você definir a sua.
5. Em **Administração → Colaboradores** (só o administrador vê) cadastre as outras pessoas: o sistema gera uma senha temporária por pessoa e a mostra uma vez. Quem esquecer a senha pede ao administrador o botão **Nova senha**.

**Para voltar ao login só com e-mail (teste):** `sed -i 's/^AUTH_MODE=.*/AUTH_MODE=mock/; s/^OIDC_MODE=.*/OIDC_MODE=mock/' .env` e `sudo docker compose up -d --force-recreate api web` (o `OIDC_MOCK_SECRET` do `.env` já existe).

Os sensores e a extensão **não mudam**: eles usam chaves de API, não a senha do console. Limites: não há envio de e-mail (a recuperação é pelo administrador), nem segundo fator, nem lista de senhas comuns (só a regra acima); o login corporativo (OIDC/SSO) segue sem teste contra provedor real.

## 11. Parar e apagar (para não pagar à toa)

- **Pausar**: EC2 → Instances → **Instance state → Stop**. Não cobra computação, mas o disco continua cobrando; o IP público muda ao religar (sem Elastic IP).
- **Encerrar de vez** (apaga os dados de teste): na VM, `docker compose down -v`; depois EC2 → **Instance state → Terminate**. Confira que o volume EBS sumiu (EC2 → Volumes), libere o Elastic IP se criou um, apague o par de chaves e o grupo de segurança se não for reusar, e **revogue a chave e os tokens** no console.

## Se você quiser acessar sem túnel (opcional, menos seguro)

Siga a seção "Sem túnel" de `docs/teste-vm.md` (`infra/expose.sh`). Na AWS isso significa **editar o grupo de segurança** e adicionar uma regra **só para o seu IP** nas portas que o script mostrar (3000 e/ou 8000, ou as altas que você escolher). O tráfego passa a ir em **HTTP sem cifra**, com login mock: não faça isso com dados que importam.

## O que este guia NÃO cobre (e não está construído)

- HTTPS com domínio e certificado, e login corporativo (OIDC): pendentes (`docs/dominio-e-assinatura.md`).
- Banco gerenciado (RDS), contêineres gerenciados (ECS/EKS), backup em S3, balanceador: **não construídos**. A decisão de nuvem de produção está em aberto (`docs/decisoes.md`).
- Várias máquinas de funcionários enviando para este servidor: exige HTTPS e login real antes.
- Pentest, revisão jurídica e executável assinado: pendentes (README, "Estado").
