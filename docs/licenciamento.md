# Licenciamento on-premise: venda, ativação, renovação e estados

Status: **construído e testado com dados sintéticos, em processo e em banco real de teste. Nunca rodou entre duas máquinas de verdade, nem com um cliente.** Decisão do dono do produto em 2026-10-27 (exceção ao "não construir on-premise agora" do `CLAUDE.md`: só o fluxo de licenciamento, não o instalador nem a atualização automática). No SaaS e no desenvolvimento nada disto liga (`LICENSE_MODE=off`, o padrão).

## Visão geral

```
FORNECEDOR (você)                                   CLIENTE (servidor dele)
serviço de licenças  <------ pedido assinado ------  produto (API + worker)
 apps/licensing                                      apps/api: license_client
 banco próprio, chave privada Ed25519                chave PÚBLICA do fornecedor fixada;
                      ------ autorização assinada -> chave privada DA INSTALAÇÃO nunca sai dela
```

Duas bibliotecas/serviços novos:

| Peça | Onde | Faz |
|---|---|---|
| `packages/licensing` | biblioteca pura | assinatura Ed25519, autorização, pedidos assinados da instalação, máquina de estados |
| `apps/licensing` (`lic_service`) | serviço do fornecedor | contratos, códigos de ativação, instalações, autorizações emitidas, auditoria, CLI de administração |
| `apps/api/app/license_client.py` | produto do cliente | identidade da instalação, ativar, renovar, estado, bloqueios; o worker renova sozinho |

## Fluxo de venda e ativação

1. **Você cadastra o cliente e o contrato** (CLI do serviço): máquinas permitidas, meses, tolerância, o que acontece ao encerrar.
2. **Gera um código de ativação** de uso único e prazo curto (padrão 7 dias). O texto aparece uma vez; no banco fica só o hash.
3. **O administrador do cliente** abre o console, vai em **Licença** e informa o código.
4. **A instalação cria a própria identidade**: par de chaves Ed25519 gerado no servidor do cliente (arquivo 0600 em `LICENSE_STATE_DIR`). A chave privada nunca sai de lá.
5. **Seu serviço valida** o código (existe, não usado, não expirado, contrato não encerrado, nenhuma outra instalação vinculada) e confere a **assinatura do pedido** (prova que quem pede tem a chave privada). Então vincula o contrato à chave **pública** da instalação e **o prazo do contrato começa a contar** (fim = ativação + meses).
6. **Devolve uma autorização assinada**, ligada àquela instalação. O produto confere a assinatura com a chave pública do fornecedor, que está **fixada** na configuração (nunca é baixada).

```bash
# no servidor do fornecedor (docker compose --profile vendor up -d licensing; ou direto com python)
python -m lic_service.cli gen-key                                  # uma vez: guarde LICENSE_SIGNING_KEY; a chave pública vai no produto do cliente
python -m lic_service.cli create-customer --name "Acme Ltda" --email ti@acme.example
python -m lic_service.cli create-contract --customer <id> --devices 100 --months 12 --tolerance-days 15 --on-end stop_inspection
python -m lic_service.cli issue-code --contract <id> --days 7      # entregue o código ao administrador do cliente
python -m lic_service.cli contracts                                # todos os contratos, estado e último contato
```

## Política semanal e suspensão por falta de validação (2026-11-11)

Além dos prazos abaixo, cada contrato pode ter `warn_after_days` e `suspend_after_days` (assinados na autorização). Contratos novos criados pelo painel usam: validar toda semana, avisar o **cliente**
após 10 dias sem validar, **suspender a inspeção** após 21 (contados do momento em que a validação era esperada, ou seja, `issued_at` + cadência) e autorização de 28 dias. O estado novo **`suspenso`**
para a inspeção e bloqueia alterações (consulta e exportação continuam; sensores seguem em falha aberta) e volta sozinho na próxima validação bem-sucedida. Quem acompanha a falha antes do cliente é o
fornecedor, no painel. Detalhes e operação: `docs/painel-fornecedor.md`. Contratos sem esses campos mantêm a regra antiga.

## Os dois prazos

| Prazo | Quem define | O que significa |
|---|---|---|
| **Contrato** (`contract_start`..`contract_end`) | você, no contrato | até quando o cliente tem direito ao produto |
| **Autorização** (`auth_expires`) | o serviço, em cada renovação (padrão 7 dias) | por quanto tempo a instalação funciona **sem** falar com você |

Regra do código, testada: uma autorização **ativa nunca passa do fim do contrato + tolerância** (a tolerância é explícita no contrato; sem tolerância corta no fim do contrato). Não se emite autorização ativa depois da tolerância. Se um serviço com bug ou chave vazada assinasse algo além disso, **o produto também recusa** (a regra é verificada dos dois lados).

O servidor do cliente renova **uma vez por dia** (`renew_after_hours`, padrão 24) pelo worker. Se o serviço estiver fora do ar, ele tenta de novo a cada 15 minutos e continua funcionando com a autorização que tem. Os prazos de exemplo (24 h e 7 dias) precisam refletir o contrato e a disponibilidade que **você** consegue oferecer.

## Estados (função pura, testada: `packages/licensing/.../states.py`)

| Estado | Quando | Matrícula de máquinas | Inspeção | Consulta e exportação |
|---|---|---|---|---|
| **Não ativado** | instalação nova ou autorização ilegível | não | **parada** | sim |
| **Ativo** | autorização válida e contrato dentro do prazo | sim | sim | sim |
| **Sem contato** | a renovação falhou por rede e já passou 1,5 período; a autorização ainda vale | sim | sim | sim |
| **Em tolerância** | contrato venceu, dentro da tolerância | sim | sim | sim |
| **Expirado** | passou a tolerância, ou a autorização local venceu sem renovar | não | sim | sim |
| **Suspenso** | faltou a validação por mais de `suspend_after_days` (regra acima) | não | **parada** | sim; volta sozinho na próxima validação |
| **Encerrado** | você encerrou o contrato; a instalação fica sabendo na próxima renovação | não | **conforme `on_end`**: `stop_inspection` (para) ou `keep_inspection` (continua) | sim |

Precedência: não ativado, encerrado, suspenso, expirado, em tolerância, sem contato, ativo.

**O que nenhum estado faz:** apagar dados, bloquear a leitura ou a exportação, ou interromper as ferramentas dos funcionários (os sensores ficam em falha aberta). **Se a inspeção parar, aparece** na faixa do topo do console, na página **Licença**, e nos sensores: a API responde 403 com o cabeçalho `X-PromptShield-Inspection: stopped`, o hook imprime "inspeção PARADA pela licença ou contrato da empresa" e a extensão mostra o aviso no indicador. Nos dois casos o trabalho da pessoa segue, mesmo em modo de falha fechado.

Cancelar a **próxima renovação** (o contrato simplesmente termina no fim do prazo, passando por tolerância e expirado) é diferente de **encerrar durante o contrato** (`close`). Essa diferença, a tolerância e o `on_end` **precisam estar no contrato** (revisão jurídica pendente).

### Limite honesto: não existe desligamento instantâneo
Uma instalação desconectada continua com a autorização que tem até ela vencer (até 7 dias, no exemplo). `close` só chega à instalação na próxima renovação. Para limitar isso, use autorizações mais curtas (`--auth-days`) ao custo de exigir mais disponibilidade do seu serviço.

## Segurança do desenho

- **Chave do fornecedor**: Ed25519, privada só no serviço (variável `LICENSE_SIGNING_KEY`); pública **fixada** em cada produto (`LICENSE_PUBLIC_KEY`). Um servidor falso não ativa (testado).
- **Identidade da instalação**: cada pedido (ativação e renovação) é assinado com a chave privada dela; o serviço confere com a chave pública cadastrada na ativação. Quem só sabe o identificador não renova (testado).
- **Repetição**: janela de ±5 minutos e nonce único (guardado por 1 hora).
- **Reversão**: a instalação recusa autorização com número de série menor que o já recebido (impede reapresentar uma autorização "ativa" antiga no lugar de uma "encerrada") e guarda o maior horário já visto (relógio voltado não ressuscita licença vencida). Limite: quem controla a máquina inteira (disco e relógio) pode tentar derrotar isto; é proteção contra erro e contra o cliente comum, não contra um atacante com acesso total.
- **Adulteração**: mexer na autorização guardada (por exemplo, o limite de máquinas) invalida a assinatura (testado).
- **Separação de domínio**: pedidos e autorizações têm prefixos diferentes e a assinatura cobre o prefixo.
- **Código de ativação**: 192 bits, uso único (trava de linha no banco; 6 instalações disputando um código: uma vence, testado), validade curta, só o hash guardado, limite de tentativas.
- **Auditoria** do serviço: só de inserção (gatilho no banco); recusas também ficam registradas.
- Criptografia: biblioteca `cryptography` (Ed25519). Nada de criptografia escrita à mão.

## Operação diária do fornecedor (manual, de propósito)

```bash
python -m lic_service.cli show --contract <id>                 # contrato, códigos, instalação, última autorização
python -m lic_service.cli extend --contract <id> --months 12   # renovação do contrato (a instalação vê na próxima renovação, até 24 h)
python -m lic_service.cli set-devices --contract <id> --devices 150
python -m lic_service.cli close --contract <id> --reason "cancelado a pedido"   # encerra durante o contrato
python -m lic_service.cli reopen --contract <id>
python -m lic_service.cli unbind --contract <id>               # troca de servidor do cliente: exige código novo; o prazo NÃO recomeça
python -m lic_service.cli audit --contract <id>
```

Venda e renovação à mão no começo; cobrança automática só depois de validar o fluxo com clientes (fora do escopo, `CLAUDE.md`).

## Configuração no servidor do cliente

```
LICENSE_MODE=onprem
LICENSE_SERVER_URL=https://licencas.seudominio.com.br
LICENSE_PUBLIC_KEY=<chave pública do fornecedor>
# o compose já monta o volume `licensedata` em /var/lib/promptshield (guarda a chave privada da instalação; PRECISA persistir e entrar no backup)
```

Perder o volume `licensedata` = perder a identidade: a instalação vira "não ativada" e você precisa fazer `unbind` e emitir um código novo. O limite de máquinas efetivo é o **menor** entre o do tenant e o da autorização. Na versão atual, o limite vale por tenant (o servidor on-premise do cliente é esperado com um tenant só).

## Como validar

**1. Automático (já existe e roda no CI):**

```bash
make test        # inclui packages/licensing (12 testes), apps/licensing (17) e apps/api/tests/test_license_onprem.py (12)
cd packages/licensing && pytest -q                                        # assinatura, prazos, estados, pedidos
cd apps/licensing && DATABASE_URL_TEST=postgresql+psycopg://... pytest -q # serviço contra PostgreSQL real: código único, corrida, prazos, encerrar, auditoria
cd apps/api && DATABASE_URL_TEST=... pytest tests/test_license_onprem.py  # produto + serviço reais em processo, relógio injetado
```

Os testes cobrem: ativação ponta a ponta; código usado, expirado, inventado; corrida de 6 instalações; pedido repetido, fora da janela ou com chave alheia; renovação a cada 24 h (e sem tráfego antes); serviço fora do ar (sem contato, depois expirado, voltando a ativo); fim do contrato, tolerância e corte da autorização; encerrar com cada política e reabrir; limite de máquinas; servidor falso; autorização adulterada, antiga e sem identidade; relógio voltado; modo desligado sem efeito. Os sensores têm testes próprios (hook em Python; extensão no Chromium).

Foi verificado que removendo de propósito a trava de uso único, o nonce ou o bloqueio de inspeção, testes falham (os testes protegem de verdade).

**2. Ensaio manual em duas máquinas (a fazer; não executado):**
1. Máquina A (fornecedor): `docker compose --profile vendor up -d licensing`, `gen-key`, cadastre cliente e contrato de **1 mês**, emita o código.
2. Máquina B (cliente): suba o produto com `LICENSE_MODE=onprem`, `LICENSE_SERVER_URL` e `LICENSE_PUBLIC_KEY`. O console deve mostrar a faixa vermelha "Instalação sem ativação" e o hook deve avisar "inspeção PARADA".
3. Ative pelo console (**Licença**). A faixa some; um prompt de teste aparece em **Todos os prompts**.
4. Derrube o serviço (A) por 2 dias e veja "Sem contato" depois de ~36 h; por 8 dias, "Expirado" (inspeção continua, matrícula não).
5. Faça `close` (cada política) e confira o que o console e os sensores mostram; `reopen` e **Renovar agora** devem restaurar.
6. Mude o relógio da máquina B para trás: a licença vencida não pode voltar.
7. Perca o volume `licensedata` de propósito e recupere com `unbind` + código novo.

**3. Só um cliente real valida:** latência e disponibilidade do seu serviço, relógio/NTP em servidor de cliente, proxy corporativo que bloqueia a saída para o serviço de licenças (e o que o cliente precisa liberar), o texto do contrato, e se os prazos de exemplo (24 h, 7 dias, 15 dias de tolerância) servem ao seu negócio.

## O que não existe ainda

O painel web do fornecedor passou a existir em 2026-11-11 (`docs/painel-fornecedor.md`). Continuam sem existir:


Aviso **por e-mail** (30/15/7 dias antes e no vencimento; a faixa no console nos últimos 30 dias do contrato já existe), cobrança e nota fiscal, assinatura do instalador/executável, vários tenants com um limite de máquinas **compartilhado**, rotação da chave do fornecedor (a instalação fixa uma chave; trocar exigiria aceitar duas), modo totalmente offline (sem nenhuma renovação, com arquivo de licença levado por pendrive), e a revisão jurídica do contrato.


## Avisos de versão e atualização
A resposta da validação semanal também carrega avisos assinados de versão da aplicação e de pacote de regras. Fluxo, formato e limites em [`pacotes-de-regras.md`](pacotes-de-regras.md).
