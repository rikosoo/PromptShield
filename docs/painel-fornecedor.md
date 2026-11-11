# Painel do fornecedor, pacote do cliente e a regra de validação

Status em 2026-11-11: **construído e testado com dados sintéticos** (serviço contra PostgreSQL real, painel por requisições HTTP, instalador com um Docker de
mentira). **Nunca rodou entre duas máquinas reais, nem com um cliente, e o instalador nunca rodou com Docker de verdade** (`instalar.ps1` nem teve a sintaxe
conferida: não há PowerShell neste ambiente). Este documento é só para **você, o fornecedor**; o cliente recebe o `LEIA-ME.md` que vai dentro do pacote.

## O desenho em uma figura

```
SEU SERVIDOR (só você)                                     SERVIDOR DO CLIENTE
┌──────────────────────────────┐   HTTPS, assinado         ┌────────────────────────────┐
│ Serviço de licenças          │ <───── valida toda semana ─│ PromptShield (só a aplicação)│
│  • /v1/activate, /v1/renew   │ ──── autorização assinada ─>│  • guarda a autorização      │
│  • /painel (só você, com VPN)│                            │  • aplica 10 e 21 dias        │
│ Painel: contratos, dias,     │      você manda o .zip     │  • dados ficam AQUI          │
│ códigos, pacotes, auditoria  │ ─────── e o código ──────> │                              │
└──────────────────────────────┘   (por canais diferentes)  └────────────────────────────┘
```

O painel **nunca** vai para o cliente. O cliente recebe a aplicação e uma **autorização assinada** pela sua chave; quem decide o estado (ativo, aviso, suspenso)
é a regra pública da biblioteca `promptshield_licensing`, em cima do que está **assinado**: o cliente não consegue adiantar o relógio da regra.

## A regra de validação (decidida em 2026-11-11)

Contratos criados pelo painel já nascem com a política **semanal**:

| Quando (contado do momento em que a validação era esperada) | O que acontece |
|---|---|
| A instalação valida **toda semana** | Tudo normal. Cada validação traz uma autorização nova de 28 dias |
| Primeira validação que falha (alerta interno depois de 12 h de atraso) | **Só você** vê, no painel ("Sem validar há N dia(s)") |
| **10 dias** sem validar | O **cliente** passa a ver uma faixa de aviso em todas as telas, com a contagem para a suspensão |
| **21 dias** sem validar | A **inspeção de novos prompts é suspensa** e alterações ficam bloqueadas. Consulta e exportação continuam e os funcionários seguem trabalhando (falha aberta) |
| Próxima validação bem-sucedida | A suspensão **se desfaz sozinha** |

Os dias de aviso (10) e suspensão (21), a cadência (7 dias) e a validade da autorização (28) são **por contrato** e editáveis no painel (a validade precisa cobrir
cadência + suspensão, senão o painel recusa). Vazio em "avisar" ou "suspender" desliga aquela parte. Contratos antigos (sem esses campos) seguem a regra antiga.

Limites honestos:
- Se o **seu** servidor ficar fora do ar por mais de 28 dias seguidos, todos os clientes serão suspensos: a regra não distingue a sua falha da deles. Na prática a suspensão volta sozinha quando o servidor volta, mas monitore o serviço (item "Pontos de atenção" abaixo).
- Quem controla a máquina inteira (disco e relógio) pode tentar enganar a contagem; a regra protege contra erro e contra o cliente comum.
- O "alerta interno" é **só no painel** (não há envio de e-mail no produto): olhe a Visão geral com frequência (rotina abaixo).

## Subir o serviço e o painel

Na sua máquina/servidor de fornecedor (perfil `vendor` do Compose):

```bash
# 1) chave de assinatura (UMA vez; a PRIVADA fica só aqui, com backup fora do servidor)
docker compose --profile vendor run --rm licensing python -m lic_service.cli gen-key       # copie LICENSE_SIGNING_KEY para o .env
# 2) no .env: LICENSING_DB_PASSWORD, LICENSE_SIGNING_KEY, PANEL_ENABLED=true, PANEL_SECRET (openssl rand -hex 32), PACKAGES_HOST_DIR
docker compose --profile vendor up -d licensing-db licensing
# 3) o SEU acesso ao painel (senha de 12+ caracteres e código de 6 dígitos)
docker compose --profile vendor exec licensing python -m lic_service.cli create-admin --email voce@suaempresa.com.br
```

O `create-admin` mostra uma **chave** e um **link otpauth**: cadastre no aplicativo autenticador (Google/Microsoft Authenticator, 1Password, Authy...). Aparece só uma vez;
se perder, `reset-admin --email ... --new-totp`. Outros comandos: `list-admins`, `reset-admin`.

**Como alcançar o painel com segurança** (ele pode encerrar e suspender todos os clientes):
- Por padrão a porta só escuta em `127.0.0.1`. Acesse por **túnel SSH** (`ssh -L 8100:localhost:8100 usuario@seu-servidor` e abra `http://localhost:8100/painel`) ou por **VPN**.
- Se publicar em um domínio, use **HTTPS** (proxy reverso, por exemplo Caddy) e limite por **lista de IPs**. `/v1/activate`, `/v1/renew` e `/health` precisam ficar alcançáveis pelos clientes; o `/painel` **não**: bloqueie esse caminho para fora da VPN no proxy.
- Com HTTPS e domínio, `PANEL_COOKIE_SECURE=true` (padrão). `PANEL_COOKIE_SECURE=false` só para teste local sem HTTPS.
- Trocar `PANEL_SECRET` derruba todas as sessões. Trocar a senha (menu **Senha**) derruba as outras sessões da conta.

O que a proteção do painel faz: senha forte (12+ caracteres), código de 6 dígitos que **não vale duas vezes**, bloqueio por 15 minutos após 5 erros, mensagem de falha igual para qualquer causa,
cookie `HttpOnly` + `SameSite=Strict`, proteção CSRF e conferência de origem em toda alteração, cabeçalhos que impedem cache e `iframe`, e toda ação grava **o seu e-mail** na auditoria (só de inserção).

## O dia a dia

1. **Visão geral**: contratos mais urgentes primeiro. Cada linha mostra dias restantes, última validação, versão instalada, máquinas em uso contra o limite e os alertas
   (atraso de validação, cliente já avisado, suspenso, contrato perto do fim/vencido, encerrado, máquinas acima do limite, sem código válido). A caixa final lista os **pedidos recusados** dos
   últimos 7 dias (instalação não reconhecida, código inválido, pedido repetido): é o "não reconheceu" do alerta interno.
2. **Dias restantes** (na tela do contrato): defina a data de fim, ou some/tire dias, **sempre com motivo** (vai para a auditoria). Antes da ativação só dá para editar a duração em meses (o prazo começa na ativação).
   O cliente vê o novo prazo na próxima validação (até 7 dias, na política semanal).
3. **Código de ativação** (o "token" do cliente): aparece **uma única vez**, logo depois de gerado. No banco fica só o hash, então não há como ver de novo (isso é de propósito: um código guardado seria um segredo a mais
   para proteger). Se perder, gere outro: o anterior deixa de valer. Valor padrão: 7 dias, uso único.
4. **Condições**: máquinas, tolerância, o que a inspeção faz se o contrato for encerrado, cadência, validade, avisar e suspender. O botão da **política semanal recomendada** restaura 7/28/10/21.
5. **Ações com efeito no cliente**: encerrar (com motivo e confirmação), reabrir, desvincular a instalação (troca de servidor: exige código novo; o prazo não recomeça).
6. **Auditoria**: tudo, com quem fez. Não dá para editar nem apagar (gatilho no banco).

## Montar o pacote e entregar ao cliente

Numa máquina de **build** (com Docker e o repositório), não no painel:

```bash
export LICENSE_SIGNING_KEY=...            # a mesma chave do serviço
make release VERSION=0.4.0 LICENSE_URL=https://licencas.suaempresa.com.br
# gera em dist/packages/: promptshield-onprem-0.4.0.zip (+ .manifest.json assinado + .README.md)
```

Copie os três arquivos para a pasta `PACKAGES_HOST_DIR` do servidor do painel. Em **Pacotes e instalador** o painel lista cada pacote, **confere a assinatura e o SHA-256 de novo** a cada visita e só libera o download se o arquivo ainda for o que foi assinado
(um arquivo trocado na pasta aparece como "arquivo foi alterado" e **não é entregue**). Ali você lê o LEIA-ME exatamente como o cliente vai ler.

O pacote traz as imagens Docker (e o PostgreSQL), `instalar.sh` (Linux/macOS), `instalar.ps1` (Windows), `backup.sh`, o `docker-compose.yml` do cliente (sem nada seu, banco não exposto), a **chave pública** e o `LEIA-ME.md`.
Sem `--with-images` ele leva as fontes e o cliente constrói as imagens (precisa de internet): só para auditoria e teste. O zip é **reproduzível**: mesmo conteúdo, mesmo hash.

**Entrega, na ordem:**
1. No painel, **gere o código de ativação** do contrato.
2. Envie o `.zip` e o **SHA-256** (ele confere antes de instalar).
3. Envie o **código por outro canal** (telefone, outra conversa). Só o pacote não ativa nada, e um código sem o pacote também não.
4. O cliente segue o LEIA-ME. Quando ele ativar, a Visão geral mostra a instalação, a versão e as máquinas.

## Pontos de atenção (leia antes de vender)

- **Teste em duas máquinas reais** antes do primeiro cliente (roteiro em `docs/licenciamento.md`, seção "Como validar"): o instalador nunca rodou com Docker de verdade; o `.ps1` precisa ser rodado num Windows real.
- **Disponibilidade do seu servidor** importa agora (a regra de 21 dias): monitore `/health`, faça backup do banco do serviço **e da chave de assinatura** (perder a chave = ninguém mais valida; trocá-la exige reemitir pacotes e ativações).
- **Proxy corporativo** do cliente pode bloquear a saída para o seu domínio; o LEIA-ME diz o que liberar. Cliente sem internet **não** é atendido por este desenho (precisaria de licença por arquivo, ainda não existe).
- Contrato, aviso legal sobre o envio periódico (o que é enviado está no LEIA-ME, seção 6) e prazos precisam de **revisão jurídica**.
- Fora do escopo desta etapa (próximas, na ordem combinada): aviso de versão nova no console do cliente, **pacotes de regras assinados**, atualização assistida com aprovação do administrador do cliente, e-mail de aviso, cobrança.
