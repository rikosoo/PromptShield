| Conjunto | Exatos | Precisão | Recall | Falso negativo | Falso positivo (negativos) | p50 / p95 ms |
|---|---|---|---|---|---|---|
| holdout_a (guiou ajuste) | 95.9% → 95.9% | 93.9% → 94.0% | 99.0% → 99.0% | 1.0% → 1.0% | 0.0% → 0.0% (0/67) | 0.35 / 0.68 |
| holdout_b (guiou ajuste) | 97.9% → 97.9% | 96.7% → 96.7% | 100.0% → 100.0% | 0.0% → 0.0% | 0.0% → 0.0% (0/80) | 0.42 / 0.88 |
| holdout_c (guiou ajuste) | 97.0% → 97.0% | 96.0% → 96.0% | 99.0% → 99.0% | 1.0% → 1.0% | 0.0% → 0.0% (0/76) | 0.41 / 0.96 |
| holdout_d (independente) | 86.2% → 86.8% | 89.7% → 89.9% | 82.4% → 83.5% | 17.6% → 16.5% | 2.9% → 2.9% (2/70) | 0.41 / 1.03 |
| holdout_e (guiou ajuste) | 96.3% → 96.3% | 97.2% → 97.2% | 98.6% → 98.6% | 1.4% → 1.4% | 0.0% → 0.0% (0/21) | 0.44 / 0.87 |
| holdout_f (independente) | 90.2% → 91.0% | 98.9% → 98.9% | 87.6% → 88.6% | 12.4% → 11.4% | 0.0% → 0.0% (0/39) | 0.45 / 0.89 |
| holdout_g (guiou ajuste) | 100.0% → 100.0% | 100.0% → 100.0% | 100.0% → 100.0% | 0.0% → 0.0% | 0.0% → 0.0% (0/22) | 0.47 / 0.65 |
| holdout_h (independente) | 91.2% → 91.2% | 100.0% → 100.0% | 86.4% → 86.4% | 13.6% → 13.6% | 0.0% → 0.0% (0/25) | 0.41 / 0.68 |
| holdout_i (guiou ajuste) | 69.8% → 100.0% | 100.0% → 100.0% | 61.3% → 100.0% | 38.7% → 0.0% | 0.0% → 0.0% (0/33) | 0.25 / 0.53 |

| Categoria | TP | FP | FN | Precisão | Recall | Coberta |
|---|---|---|---|---|---|---|
| alteracao_permissao | 20 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| arquitetura | 10 | 1 | 0 | 91% → 91% | 100% → 100% | sim |
| cliente | 22 | 0 | 2 | 100% → 100% | 92% → 92% | sim |
| codigo_proprietario | 11 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| conteudo_toxico | 22 | 0 | 1 | 100% → 100% | 96% → 96% | sim |
| envenenamento_mcp | 6 | 4 | 0 | 60% → 60% | 100% → 100% | sim |
| escrita_fora_projeto | 18 | 2 | 0 | 90% → 90% | 100% → 100% | sim |
| estrategia_ma | 20 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| exfiltracao_ferramenta | 12 | 7 | 0 | 63% → 63% | 100% → 100% | sim |
| extracao_system_prompt | 25 | 1 | 4 | 96% → 96% | 86% → 86% | sim |
| financeiro | 54 | 2 | 0 | 96% → 96% | 83% → 100% | sim |
| iac | 12 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| injection_direta | 36 | 1 | 6 | 97% → 97% | 83% → 86% | sim |
| injection_indireta | 15 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| instalacao_pacote | 7 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| jailbreak | 23 | 2 | 3 | 92% → 92% | 88% → 88% | sim |
| juridico | 26 | 1 | 1 | 96% → 96% | 96% → 96% | sim |
| leitura_env | 42 | 2 | 1 | 95% → 95% | 98% → 98% | sim |
| logs | 6 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| pii | 105 | 4 | 5 | 96% → 96% | 95% → 95% | sim |
| propriedade_intelectual | 2 | 0 | 0 | 100% → 100% | 100% → 100% | sim |
| rede_externa | 28 | 3 | 0 | 90% → 90% | 100% → 100% | sim |
| revisao_codigo | 7 | 0 | 1 | 100% → 100% | 88% → 88% | sim |
| rh | 47 | 1 | 6 | 98% → 98% | 89% → 89% | sim |
| saude | 40 | 0 | 1 | 100% → 100% | 98% → 98% | sim |
| segredo | 122 | 0 | 1 | 100% → 100% | 81% → 99% | sim |
| shell_destrutivo | 39 | 0 | 1 | 100% → 100% | 98% → 98% | sim |
| sql | 8 | 1 | 0 | 89% → 89% | 100% → 100% | sim |
| uso_pessoal | 37 | 0 | 3 | 100% → 100% | 92% → 92% | sim |
