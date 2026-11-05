# PromptShield — contexto do projeto

## O que estamos construindo
Plataforma SaaS B2B multi-tenant que observa o uso de IA por funcionários e agentes (prompts, respostas, ações de agentes), classifica cada evento em categorias, calcula um risco explicável e aplica políticas (permitir, mascarar, bloquear, pedir justificativa). Pense em um "Defender para IA".
O núcleo é: coletor -> evento universal -> motor de detecção -> política -> console. Cada IA entra por um adaptador; o motor nunca sabe de onde veio o evento.

## Princípios inegociáveis
1. Honestidade técnica: nunca presumir que uma ferramenta expõe prompts. Para cada integração, classificar como REAL (documentada e testada), PARCIAL ou EXPERIMENTAL, e dizer isso no código e na documentação.
2. Nada de captura oculta: sem keylogger, sem captura indiscriminada, sem contornar proteções de aplicativos. A coleta é transparente, limitada aos domínios e ferramentas configurados pelo administrador, e mostra aviso ao usuário.
3. Privacidade por padrão: guardar o texto já mascarado. O texto original só é guardado se o tenant ativar, cifrado; ver o original exige justificativa e gera registro de auditoria. Retenção configurável.
4. Nenhum conteúdo de cliente vai para LLM externo. A classificação usa regras e modelos pequenos que rodam localmente. Integração com LLM externo, se existir, fica desligada por padrão e exige configuração explícita do tenant.
5. Dados sintéticos em testes e demonstrações, sempre rotulados como simulados. Nunca usar dados reais.
6. Não inventar: APIs, formatos e protocolos de terceiros (Anthropic, OpenAI, Microsoft etc.) devem ser lidos na documentação oficial antes de implementar. Se não der para verificar, marcar "A VERIFICAR" e não fingir que funciona.
7. Padrão seguro: toda política nasce em modo só monitorar (sombra). Bloquear é opt-in por política.

## Stack do MVP
- Backend e motor de detecção: Python 3.12, FastAPI, SQLAlchemy + Alembic, Pydantic. Um único serviço no início, dividido em módulos.
- Banco: PostgreSQL com row-level security por tenant. Redis só se for realmente necessário.
- Console: Next.js, React, TypeScript, Tailwind. Tema claro por padrão, com alternância para escuro, estilo de consoles de segurança.
- Extensão: TypeScript, Manifest V3, Chrome e Edge.
- Local: Docker Compose sobe tudo com um comando. A nuvem de produção ainda não foi decidida; não escrever nada específico de AWS ou Azure.
- Testes: pytest no backend, vitest no front e na extensão, Playwright para o fluxo principal.

## Estrutura do repositório
apps/api, apps/web, apps/extension,
packages/detection (biblioteca pura, sem dependência de web),
packages/adapters (claude_code_hook, inference_hooks, browser),
packages/taxonomy (taxonomy.yaml),
docs/, infra/, tests/fixtures (dados sintéticos)

## Evento universal
Todo coletor traduz o que captura para este formato. O motor só conhece este formato.
```json
{
  "event_id": "uuid",
  "tenant_id": "uuid",
  "occurred_at": "2026-10-13T20:00:00Z",
  "source": { "channel": "browser | agent_hook | api_proxy | inference_hook", "app": "claude_code | chatgpt_web | ...", "integration_status": "real | partial | experimental" },
  "actor": { "user_id": "...", "department": "...", "device_id": "...", "agent_id": null },
  "kind": "prompt | response | tool_call | tool_result | file_upload",
  "content": { "text": "...", "tool_name": null, "tool_input": null },
  "context": { "session_id": "...", "personal_account": false }
}
```
Resultado da análise:
```json
{
  "categories": [{ "id": "segredo", "confidence": 0.97 }],
  "flags": { "has_code": true, "has_sensitive": true, "is_agent_action": false },
  "risk": { "score": 0-100, "reasons": [{ "rule": "...", "contribution": 0 }] },
  "spans": [{ "start": 0, "end": 0, "type": "aws_key", "masked": "AKIA****" }],
  "decision": "allow | mask | block | ask_justification | alert"
}
```

## Ações de política
allow, mask (substituir trechos sensíveis), block, ask_justification, alert. Cada política tem escopo (tenant, departamento, ferramenta, grupo) e modo (monitor ou enforce).

## Taxonomia inicial: 30 categorias (ids em packages/taxonomy/taxonomy.yaml)
Dados sensíveis: pii, financeiro, saude, segredo, cliente, rh.
Código e engenharia: codigo_proprietario, iac, sql, logs, arquitetura, revisao_codigo.
Ataques à IA: injection_direta, injection_indireta, jailbreak, extracao_system_prompt, exfiltracao_ferramenta, envenenamento_mcp.
Ações de agente: shell_destrutivo, leitura_env, rede_externa, escrita_fora_projeto, instalacao_pacote, alteracao_permissao.
Negócio: estrategia_ma, juridico, propriedade_intelectual, conteudo_toxico, uso_pessoal, produtividade_legitima.
Cada categoria tem: id, nome em pt-BR, grupo, risco padrão, método de detecção, exemplos sintéticos positivos e negativos.
OWASP LLM Top 10 e MITRE ATLAS só entram depois de abrir as versões atuais; citar a versão usada.

## Regras de trabalho
- Trabalhe em passos pequenos. Rode os testes antes de dizer que terminou e mostre a saída.
- Ao fim de cada etapa, escreva um relatório curto: o que funciona (com o comando que prova), o que é simulado, o que ficou pendente, riscos novos.
- Nunca apresente código de exemplo como implementação concluída.
- Se uma decisão é cara de desfazer, pare e pergunte.
- Commits pequenos com mensagem clara. Nenhum segredo no repositório; só .env.example.
- Mantenha README, docs/arquitetura.md e docs/decisoes.md atualizados (uma linha por decisão: contexto, escolha, alternativas).

## Não construir agora
Agente de desktop, proxy ou gateway de rede, empacotamento completo da versão on-premise (instalador, atualização automática; **exceção decidida em 2026-10-27 pelo dono do produto: o fluxo de licenciamento on-premise** — serviço de licenças separado, ativação por código, autorização assinada e renovação periódica — pode ser construído, ver `docs/licenciamento.md`), cobrança automática e planos, conectores além dos listados nas etapas, SSO corporativo completo (começar com OIDC genérico), modelos de machine learning treinados do zero.
