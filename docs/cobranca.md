# Plano de cobrança, limitação por inadimplência e arquitetura

**Status: PROPOSTA. Nada de cobrança está construído.** O que existe hoje e é usado aqui: licença com dois prazos e cinco estados (`docs/licenciamento.md`), suspensão reversível no SaaS (`docs/operacao.md`), CLI do fornecedor (`extend`, `close`, `reopen`, `unbind`, `suspend`, `resume`) e a contagem de máquinas ativas que a instalação informa a cada renovação. Cobrança automática está em "não construir agora" no `CLAUDE.md`: as fases 1 em diante abaixo só começam depois de o dono do produto registrar a exceção, como foi feito com o licenciamento. Preços, prazos, índices, multas e regras fiscais são **exemplos a validar** com um contador e um advogado (**A VERIFICAR**); eu não consultei fornecedores nem legislação.

## 1. Princípios (valem para tudo abaixo)

1. **Pagar é um processo humano e financeiro.** O produto só interpreta o resultado (contrato ativo ou encerrado). Ele nunca decide cortar por conta própria.
2. **Nada apaga dados e nada interrompe as ferramentas dos funcionários** como forma de cobrança. Parar a inspeção é o último degrau, só se o contrato disser, com aviso prévio, e fica visível no console e nos sensores.
3. **Toda restrição passa por aprovação humana no início** e é reversível quando o pagamento entra. A cobrança nasce em **modo sombra** (só lista o que faria), como as políticas do produto.
4. **Venda e cobrança manuais primeiro.** Automatizar antes de ter clientes pagando adiciona trabalho sem validar a demanda.
5. **Dados de cartão nunca passam pelo produto nem pelo seu servidor.** Pagamento acontece numa página do provedor.
6. **Quem não paga tem o contrato, não a licença, como cobrança de última instância.** A licença é um incentivo, não uma garantia (ver seção 4).

## 2. O que cobrar

| Item | Proposta | Observação |
|---|---|---|
| **Métrica** | Pacote de **máquinas ativas** (25, 50, 100, 250, 500...) | É o que a licença já limita (`max_devices`, ativas nos últimos 45 dias). Cobrar por usuário exigiria mudar a licença. |
| **Prazo** | Contrato **anual** | Pagamento anual antecipado com desconto, ou mensal; escolha por cliente. |
| **Piloto** | 30 a 60 dias, valor fixo, **abatido** se fechar | Valida disposição de pagar antes de definir preço de lista. |
| **Implantação** | Taxa única para on-premise/enterprise | Cobre o acompanhamento da instalação e da primeira configuração. |
| **Excedente** | **Não há cobrança automática.** Ao atingir o limite, novas matrículas ficam bloqueadas | Ajuste ("true-up") na renovação pelo **pico** de máquinas ativas; o serviço de licenças já recebe a contagem a cada renovação. |
| **Reajuste** | Anual por índice previsto em contrato | Qual índice: **A VERIFICAR** com o advogado. |
| **Preço** | Não definido | Definir com 1 a 3 pilotos. Os valores por usuário citados em conversa anterior eram hipóteses, não preços de mercado. |

Exemplo de conta (hipotético, só para dimensionar): 100 máquinas a R$ X por máquina por mês, contrato anual, dá 12 parcelas ou uma anual com desconto. Defina X depois dos pilotos.

## 3. Linha do tempo de cobrança (padrão sugerido; o contrato manda)

Dois caminhos diferentes, que **precisam estar no contrato**: não renovar (o contrato simplesmente termina) e atrasar durante o contrato (inadimplência de parcela).

### 3.1 Renovação anual não paga

V = data de término do contrato. A tolerância é a do contrato (padrão 15 dias).

| Quando | Cobrança (humano) | Produto | Quem decide |
|---|---|---|---|
| V-60 | Proposta de renovação e reajuste | Nada | Você |
| V-30 | Fatura emitida, lembrete | Faixa amarela "Contrato perto do fim" no console (on-premise: nos últimos 30 dias; SaaS: nos últimos 15) | Automático |
| V-15 | Segundo lembrete ao administrador e ao financeiro | Faixa amarela | Automático |
| V | Se pago: `extend`. Se não: aviso de vencimento | **Ativo** vira **Em tolerância**; console mostra o prazo | Automático |
| V+15 | Aviso: tolerância terminou | **Expirado**: sem novas máquinas; inspeção, consulta e exportação continuam | Automático |
| V+45 | Notificação formal de encerramento (15 dias) | Igual | Você, com texto do advogado |
| V+60 | Encerramento (`close`) | **Encerrado** com a política do contrato (`keep_inspection` ou `stop_inspection`) | **Você aprova** |
| V+90 | Aviso final de apagamento (30 dias para exportar) | Console só lê e exporta | Você |
| V+120 | Apagamento dos dados, com comprovante | Dados removidos | Você, conforme contrato e LGPD |

### 3.2 Parcela mensal em atraso durante o contrato

D = vencimento da fatura.

| Quando | Cobrança | Produto | Quem decide |
|---|---|---|---|
| D+1 | Lembrete (e-mail) | Nada | Automático |
| D+5 | Aviso ao financeiro e ao administrador | Nada | Automático |
| D+15 | Notificação formal de inadimplência (cláusula contratual) | Nada | Você |
| D+30 | **Proposta de restrição** (aparece no painel; nada acontece sozinho) | SaaS: `suspend`. On-premise: `close --reason inadimplencia` com a política do contrato | **Você aprova** |
| D+60 | Rescisão conforme contrato | Fluxo de encerramento da seção 3.1 | Você |
| Pago | Baixa da fatura | SaaS: `resume`. On-premise: `reopen`; a instalação vê em até 24 h ou o administrador clica em **Renovar agora** | Automático depois da baixa confirmada |

Pagamento por boleto leva dias para compensar: **nenhuma restrição acontece enquanto houver pagamento em compensação**.

## 4. Como limitar quando a empresa não paga

### Escada de limitação (do mais leve ao mais pesado)

| Degrau | Efeito | Existe hoje? | Reversível |
|---|---|---|---|
| 1. Avisos (faixa, e-mail) | Informar | Faixa: SaaS a 15 dias do fim; on-premise a 30 dias do fim; os dois depois de vencer. **E-mail: não existe.** | Sim |
| 2. Não renovar a autorização | A autorização local (7 dias) vence | Sim (`close` ou contrato vencido) | Sim |
| 3. Bloquear novas matrículas | **Expirado** no on-premise | Sim | Sim |
| 4. Console somente leitura | Alteração recusada; consulta e exportação ficam | Sim (SaaS suspenso; on-premise com inspeção parada) | Sim |
| 5. **Parar a inspeção** | Coletores recusados; **aviso nos sensores e no console** | Sim (`suspend` no SaaS; `close` com `stop_inspection` no on-premise) | Sim |
| 6. Apagar dados | Irreversível | **Não existe** e não recomendo como cobrança | Não |
| 7. Interromper as ferramentas dos funcionários | Nunca | Os sensores são "falha aberta" | n/a |

Recomendação de padrão para contratos novos: degraus 1 a 4 automáticos; o 5 só no encerrado, com a política escolhida **no contrato** e aprovação sua; o 6 só depois do prazo de exportação.

### Limites honestos
- **Não existe desligamento instantâneo** enquanto a instalação puder funcionar desconectada: o limite real é o prazo da autorização (7 dias no exemplo). Autorização mais curta aperta o limite e exige mais disponibilidade do seu serviço.
- Quem controla o servidor inteiro (disco e relógio) pode tentar derrotar a licença. Ela protege contra erro e contra o cliente comum, não contra um atacante com acesso total.
- **A cobrança de última instância é jurídica** (cobrança, protesto, ação), não técnica.
- Parar uma ferramenta de segurança do cliente pode deixar o cliente sem visibilidade. O contrato precisa prever essa consequência e isentar o fornecedor, e o aviso prévio é parte da proteção.
- Um erro seu de cobrança (fatura paga e não baixada) nunca deve parar a inspeção de um cliente: por isso aprovação humana, janela de compensação, pausa por disputa e reconciliação diária.

## 5. Arquitetura proposta

```
                              FORNECEDOR (você)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  Back-office (CLI hoje; web depois)                                       │
 │     │ clientes, contratos, faturas, pagamentos, casos de cobrança          │
 │     ▼                                                                      │
 │  ┌───────────────┐  baixa de pagamento   ┌──────────────────────────────┐ │
 │  │ MÓDULO DE      │ ───────────────────▶ │ SERVIÇO DE LICENÇAS (existe)  │ │
 │  │ COBRANÇA (novo)│  extend/reopen/close │ contratos, códigos,           │ │
 │  │ faturas,       │ ◀─────────────────── │ autorizações, auditoria       │ │
 │  │ pagamentos,    │  estado do contrato  └───────────────┬──────────────┘ │
 │  │ casos, avisos  │                                       │ autorização    │
 │  └───┬───────┬────┘                                       │ assinada (24h) │
 │      │       │ e-mail transacional                        │                │
 │      │       └──────────▶ (SMTP/provedor)                 │                │
 │      │ cria cobrança / recebe webhook assinado            │                │
 └──────┼────────────────────────────────────────────────────┼────────────────┘
        ▼                                                    ▼
 ┌─────────────────────┐                     ┌────────────────────────────────┐
 │ GATEWAY DE PAGAMENTO │                     │ SERVIDOR DO CLIENTE (existe)   │
 │ (externo) boleto,    │                     │ produto + license_client        │
 │ Pix, cartão          │                     │ estado: ativo / sem contato /  │
 └─────────────────────┘                     │ tolerância / expirado /        │
        ▲                                     │ encerrado → console e sensores │
        │ NFS-e: contador ou provedor         └────────────────────────────────┘
        └─ (fora do produto no início)
```

O **produto do cliente não conhece dinheiro**: só vê o estado do contrato na autorização. Toda a lógica financeira fica do lado do fornecedor.

### Componentes

| Componente | Situação | Função |
|---|---|---|
| Serviço de licenças | Existe | Contratos, códigos de ativação, instalações, autorizações assinadas, auditoria |
| `license_client` no produto | Existe | Renova, interpreta os estados, bloqueia matrícula, avisa |
| **Módulo de cobrança** | Novo (mesmo serviço, esquema separado) | Faturas, pagamentos, casos de cobrança, avisos, propostas de restrição |
| Gateway de pagamento | Externo; escolha **A VERIFICAR** | Página de pagamento (boleto, Pix, cartão) e webhook assinado |
| NFS-e | Externa no início (contador) | Nota fiscal de serviço; integração só se o volume justificar |
| E-mail transacional | Externo | Avisos de vencimento e atraso |
| Back-office | CLI hoje | Painel web simples depois |

### Dados do módulo de cobrança (esboço)

| Tabela | Campos principais |
|---|---|
| `invoices` | contrato, número, valor, vencimento, estado (emitida, paga, vencida, cancelada), referência no provedor, NFS-e, emitida em, paga em |
| `payments` | fatura, **id do evento do provedor (único, para idempotência)**, método, valor, pago em, hash do evento bruto |
| `dunning_cases` | contrato, fatura, estágio, próxima ação, **pausado** e motivo (disputa) |
| `dunning_actions` | caso, ação (aviso, proposta, restrição, reativação), proposta em, **aprovada por**, executada em, resultado |
| `notices` | contrato, canal, modelo, enviado em, destinatário (guardado em hash ou minimizado) |
| auditoria | só de inserção, como a do licenciamento |

### Fluxos

1. **Venda e ativação** (existe): contrato, código de uso único, ativação, autorização.
2. **Fatura e pagamento:** emitir fatura, gerar cobrança no provedor, cliente paga, **webhook assinado**, o módulo confirma o evento consultando o provedor, baixa a fatura, executa `extend` ou `reopen`/`resume`, a instalação recebe na próxima renovação (até 24 h).
3. **Cobrança (diária):** um job calcula os dias de atraso de cada fatura e avança o caso. Avisos saem sozinhos. Restrições viram **propostas**; você aprova uma a uma no painel; só então o módulo chama o serviço de licenças (`close`/`suspend`).
4. **Disputa ou ajuste:** você marca o caso como **pausado**; nenhum aviso nem proposta sai até a pausa acabar.

### Salvaguardas (o que impede o erro caro)

- **Modo sombra** no começo: o job só lista o que enviaria e proporia, como as políticas do produto.
- **Aprovação humana** para qualquer restrição; limite de ações em lote por execução.
- **Janela de compensação:** sem restrição enquanto houver pagamento pendente de compensação.
- **Idempotência** dos webhooks e **reconciliação diária** com o provedor (cobre webhook perdido).
- **Webhook só vale se a assinatura conferir** e o evento for confirmado consultando o provedor.
- **Pausa por disputa** e reversão em um comando.
- **Disponibilidade:** se o módulo de cobrança ou o serviço de licenças cair, **ninguém é punido**: as autorizações já emitidas continuam valendo.
- **Privacidade:** contatos financeiros são dados pessoais (LGPD): guardar o mínimo, acesso por papel (financeiro e operação separados), auditoria imutável.

## 6. Fases

| Fase | O que entra | Pré-requisito | Pronto quando |
|---|---|---|---|
| **0, agora (manual)** | Planilha ou sistema do contador, faturas por boleto ou Pix e NFS-e emitidas por ele, lembretes por e-mail à mão, restrição pela CLI | Contrato com as cláusulas da seção 7 (a faixa de aviso "contrato perto do fim" do on-premise já existe) | 3 renovações seguidas sem erro |
| **1, registro e avisos** | Faturas e pagamentos registrados no back-office, job de casos em **modo sombra**, e-mails automáticos de vencimento e atraso, painel de inadimplência | Exceção registrada no `CLAUDE.md` | O modo sombra bate com o que você faria à mão por 2 ciclos |
| **2, pagamento integrado** | Link de pagamento, webhook, baixa automática, `extend`/`reopen` automáticos, propostas de restrição com aprovação | Provedor escolhido | Reconciliação sem diferença por 2 ciclos |
| **3, autoatendimento** | Portal do cliente (faturas, 2ª via, contatos), reajuste, relatórios (receita recorrente, cancelamentos, inadimplência) | Clientes suficientes para justificar | Sob demanda |

Esforço: a fase 0 é só processo e uma faixa no console. A fase 1 é a maior parte do código (módulo, job, avisos, painel). A fase 2 depende do provedor.

## 7. Cláusulas que o contrato precisa ter (lista para o advogado)

- Objeto, prazo, **dois caminhos**: não renovação e rescisão por inadimplência.
- Preço, reajuste (índice), forma e prazo de pagamento, multa e juros de mora (**valores a validar**).
- **Tolerância** em dias e o que vale durante ela.
- **Política ao encerrar** (`keep_inspection` ou `stop_inspection`), com aviso prévio e o prazo desse aviso.
- Limite de máquinas, ajuste na renovação pelo pico, bloqueio de novas matrículas ao atingir o limite.
- Prazo para **exportar** os dados e prazo e forma de **apagamento**, com comprovante.
- Isenção de responsabilidade quando a inspeção parar por decisão contratual.
- Papel de **operador de dados** (LGPD) e aviso aos funcionários (responsabilidade do cliente).
- Limitação técnica: instalação desconectada funciona até o fim da autorização.
- Canal oficial de notificação e quem recebe (financeiro e administrador).

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Restringir por engano um cliente que pagou | Aprovação humana, janela de compensação, reconciliação, reativação em um comando |
| Webhook forjado ou perdido | Assinatura, confirmação no provedor, reconciliação diária |
| Dependência do provedor de pagamento | Fatura sempre gerável sem ele (boleto/Pix manual) |
| Cliente desconectado não é limitado | Autorização curta e cobrança jurídica; não prometer corte imediato |
| Parar a inspeção causar incidente no cliente | Aviso prévio, cláusula, política padrão `keep_inspection` até decidir diferente |
| Fiscal e tributário | Contador define regime, emissão e impostos (**A VERIFICAR**) |
| Dado pessoal de contatos financeiros | Minimização, acesso por papel, auditoria |

## 9. Decisões que são suas

1. Pagamento **anual antecipado** ou **mensal** como padrão?
2. Política padrão ao encerrar: `keep_inspection` (recomendado no começo) ou `stop_inspection`?
3. Dias de **tolerância** padrão (sugestão: 15) e de **aviso de encerramento** (sugestão: 15).
4. Prazo de **exportação** e de **apagamento** depois do encerramento.
5. **Provedor de pagamento** (preço, Pix, boleto, nota fiscal): comparar 2 ou 3, **A VERIFICAR**.
6. Quem emite a **NFS-e** (contador ou integração).
7. Quando registrar a **exceção** no `CLAUDE.md` para começar a fase 1.
