# Pacotes de regras e atualização assistida

Status: **construído e testado com dados sintéticos (processo único e banco real de teste, Docker FALSO para o script). Nunca rodou em Docker real, no Windows nem entre duas máquinas.** Decisão do dono em 2026-11-11 (exceção registrada no `CLAUDE.md`).

## Fluxo (nada é instalado sozinho)
1. O fornecedor publica uma versão da aplicação ou um pacote de regras no painel (Versões).
2. Na validação semanal da licença, a resposta traz um **aviso assinado** (inclui a assinatura do pacote). O cliente confere; aviso falso, antigo ou de versão menor é ignorado e nunca derruba a validação.
3. O administrador do cliente vê em **Administração > Atualizações** (faixa no topo só para ele) e **aprova o download**. O worker baixa para `<LICENSE_STATE_DIR>/updates/` conferindo tamanho, SHA-256 e assinatura; arquivo incorreto é descartado, nada fica pela metade.
4. **Aplicação:** o administrador roda `bash atualizar.sh` no servidor (backup antes; recusa versão menor; troca os arquivos sem tocar `.env`, dados e licença; confere a versão que a API informa). A API do cliente **nunca** toca o Docker.
5. **Regras:** guardado (sem efeito) → **sombra** (registra o que casaria, não muda categoria, risco, máscara nem decisão) → **ativo** → desativado (volta ao padrão de fábrica na hora). Um pacote vivo por vez. Cada mudança de fase vai para a auditoria.

## Formato do pacote de regras (JSON assinado "pk1")
```json
{"v":1,"typ":"rulepack","version":"2026.11.1","min_engine":"2.0","notes":"...","weights":{"segredo":90},
 "rules":[{"id":"tok-interno-x","category":"segredo","confidence":0.9,"rule":"Token interno do sistema X","kind":"regex","pattern":"\\bXTK-[A-Z0-9]{16}\\b","span_type":"xtk","masked":"XTK-****"},
          {"id":"projeto-fenix","category":"estrategia_ma","confidence":0.8,"rule":"Menção ao projeto Fênix","kind":"terms","terms":["projeto fenix"],"whole_word":true}]}
```
- Só dados: procurar padrão no texto, apontar para categoria que **já existe** na taxonomia, dar confiança/motivo/máscara e sugerir pesos. Sem rede, sem arquivos, sem código.
- Os **pesos da empresa prevalecem** sobre os do pacote.
- Montar: `make rulepack SOURCE=arquivo.json VERSION=2026.11.1` (exige `LICENSE_SIGNING_KEY`). Valida com a mesma biblioteca do cliente; se algo não valida, nenhum arquivo é gerado. Exemplo SIMULADO em `infra/release/rulepacks/exemplo.json`.
- Assinatura em domínio próprio (`promptshield-rules`): uma assinatura de pacote de regras não vale como pacote da aplicação, e vice-versa.

## Limites honestos
- `re` do Python não tem tempo limite. A validação recusa padrões que costumam explodir (repetição dentro de repetição, retrovisor, repetição acima de 200) e roda um teste de orçamento de tempo em processo separado. Isso protege contra erro de quem escreve a regra; o pacote só chega assinado pelo fornecedor.
- Pacote de regras alterado no banco do cliente tem a assinatura reconferida a cada carga: se não confere, é ignorado e o motor de fábrica segue funcionando.
- Não existe `atualizar.ps1`: no Windows a atualização é manual, com o fornecedor.
- Voltar atrás depois da migração do banco exige restaurar o backup (o script não desfaz migrações).
- Não há atualização automática de propósito.
