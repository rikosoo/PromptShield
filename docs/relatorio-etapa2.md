# Relatório da Etapa 2: motor de detecção

Conjunto: `tests/fixtures/examples.jsonl`, 425 exemplos sintéticos (139 negativos difíceis), português e inglês.

**Aviso de validade.** O conjunto e o motor foram escritos pela mesma autoria. Os números abaixo medem consistência com o gabarito sintético, não desempenho em dados reais. Esperam-se piores resultados em produção, principalmente nas categorias de negócio (dicionários).

| Categoria | Grupo | TP | FP | FN | Precisão | Recall |
|---|---|---|---|---|---|---|
| pii | Dados sensíveis | 64 | 0 | 0 | 1.00 | 1.00 |
| financeiro | Dados sensíveis | 11 | 0 | 0 | 1.00 | 1.00 |
| saude | Dados sensíveis | 3 | 0 | 0 | 1.00 | 1.00 |
| segredo | Dados sensíveis | 48 | 0 | 0 | 1.00 | 1.00 |
| cliente | Dados sensíveis | 3 | 0 | 0 | 1.00 | 1.00 |
| rh | Dados sensíveis | 3 | 0 | 0 | 1.00 | 1.00 |
| codigo_proprietario | Código e engenharia | 10 | 0 | 0 | 1.00 | 1.00 |
| iac | Código e engenharia | 9 | 0 | 0 | 1.00 | 1.00 |
| sql | Código e engenharia | 5 | 0 | 0 | 1.00 | 1.00 |
| logs | Código e engenharia | 8 | 0 | 0 | 1.00 | 1.00 |
| arquitetura | Código e engenharia | 4 | 0 | 0 | 1.00 | 1.00 |
| revisao_codigo | Código e engenharia | 5 | 0 | 0 | 1.00 | 1.00 |
| injection_direta | Ataques à IA | 6 | 0 | 0 | 1.00 | 1.00 |
| injection_indireta | Ataques à IA | 3 | 0 | 0 | 1.00 | 1.00 |
| jailbreak | Ataques à IA | 4 | 0 | 0 | 1.00 | 1.00 |
| extracao_system_prompt | Ataques à IA | 3 | 0 | 0 | 1.00 | 1.00 |
| exfiltracao_ferramenta | Ataques à IA | 5 | 0 | 0 | 1.00 | 1.00 |
| envenenamento_mcp | Ataques à IA | 4 | 0 | 0 | 1.00 | 1.00 |
| shell_destrutivo | Ações de agente | 10 | 0 | 0 | 1.00 | 1.00 |
| leitura_env | Ações de agente | 14 | 0 | 0 | 1.00 | 1.00 |
| rede_externa | Ações de agente | 9 | 0 | 0 | 1.00 | 1.00 |
| escrita_fora_projeto | Ações de agente | 10 | 0 | 0 | 1.00 | 1.00 |
| instalacao_pacote | Ações de agente | 4 | 0 | 0 | 1.00 | 1.00 |
| alteracao_permissao | Ações de agente | 4 | 0 | 0 | 1.00 | 1.00 |
| estrategia_ma | Negócio e conformidade | 3 | 0 | 0 | 1.00 | 1.00 |
| juridico | Negócio e conformidade | 3 | 0 | 0 | 1.00 | 1.00 |
| propriedade_intelectual | Negócio e conformidade | 2 | 0 | 0 | 1.00 | 1.00 |
| conteudo_toxico | Negócio e conformidade | 4 | 0 | 0 | 1.00 | 1.00 |
| uso_pessoal | Negócio e conformidade | 3 | 0 | 0 | 1.00 | 1.00 |
| produtividade_legitima | Negócio e conformidade | 24 | 0 | 0 | 1.00 | 1.00 |

## Latência (inline, sem classificador de injection)

Texto de 2000 caracteres, 300 execuções, Python 3.13.16, Linux x86_64, CPU: Intel(R) Xeon(R) Processor @ 2.10GHz, 4 núcleos (ambiente de nuvem compartilhado).

p50 9.41 ms, p95 12.80 ms, p99 14.90 ms, máx 16.54 ms. Meta: p95 < 50 ms.

## Exemplos divergentes (0)

| id | grupo | esperado | obtido | texto |
|---|---|---|---|---|

## Com NER local (Presidio + spaCy `pt_core_news_sm` e `en_core_web_sm`)

Exemplos que contêm nome de pessoa passam a esperar `pii` (30 exemplos); 11 exemplos só existem neste modo.

`pii`: precisão 1.00, recall 1.00 ({'tp': 75, 'fp': 0, 'fn': 0}).

Latência com NER: p50 43.02 ms, p95 56.89 ms, p99 59.75 ms.

Divergentes com NER (0):

