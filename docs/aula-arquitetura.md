# Aula de arquitetura do PromptShield

Para quem vai **vender** (o que é, por que é assim, o que NÃO promete) e para quem vai **programar** (onde mexer e por quê).
Estado em 2026-11-07. Versões lidas do repositório e do ambiente de testes; ver o aviso na seção 4.

## 1. O que é, em uma frase
Um "Defender para IA": observa o que funcionários e agentes enviam a ferramentas de IA, classifica cada evento, calcula um **risco explicável (0 a 100)**, registra e **alerta**. É **passivo**: nunca bloqueia nem altera um prompt (decisão do dono, 2026-11-05).

## 2. O caminho de um prompt (a ideia central)
```
coletor (adaptador) ─► evento universal ─► motor de detecção ─► pontuação ─► políticas ─► banco ─► alertas ─► console
```
- **Coletor**: um por origem (extensão do navegador, sensor/hook de CLI como Claude Code, inference hook). Cada um traduz o que captura para o mesmo formato.
- **Evento universal**: um JSON único (quem, quando, canal, app, tipo, texto). **O motor nunca sabe de onde veio o evento.** Por isso entrar uma IA nova = escrever um adaptador, sem mexer no motor.
- **Motor** (`packages/detection`): biblioteca pura, sem rede, sem banco, sem LLM externo. Roda local e on-premise.
- **API** (`apps/api`): recebe o evento, chama o motor, aplica palavras-chave e políticas, grava, abre incidente, dispara alertas.
- **Console** (`apps/web`): onde o cliente vê tudo.

**Motivo (venda):** o cliente não envia conteúdo a terceiros, e o produto cresce por adaptadores. **Motivo (código):** motor puro é testável sem subir nada.

## 3. As peças e por que cada uma existe
| Peça | Pasta | Tecnologia | Motivo |
|---|---|---|---|
| API | `apps/api` | Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic | Um serviço só, dividido em módulos: simples de operar; tipos validados na entrada |
| Motor | `packages/detection` | Python puro (regex, validadores, regras) | Explicável, offline, sem custo por chamada |
| Banco | PostgreSQL | **row-level security** por empresa | O isolamento entre clientes é garantido pelo banco, não só pelo código |
| Console | `apps/web` | Next.js, React, TypeScript, Tailwind | Padrão de mercado; tema claro/escuro |
| Extensão | `apps/extension` | TypeScript, Manifest V3, Chrome e Edge, esbuild | Lê o prompt no envio e deixa seguir; análise em segundo plano |
| Sensores de CLI | `packages/adapters` | Python (hooks) | Claude Code, Codex CLI, Copilot CLI |
| Licença on-premise | `apps/licensing`, `packages/licensing` | Serviço separado, Ed25519 | Ativação por código, autorização assinada, renovação periódica |
| Subida local | `docker-compose.yml` | Docker Compose | Um comando sobe tudo |

Redis **não** é usado (só entraria se fosse realmente necessário). Nada específico de AWS/Azure: a nuvem de produção não foi decidida.

## 4. Versões
| Item | Versão |
|---|---|
| Python | 3.12 (imagem `python:3.12-slim`) |
| Node (console e build da extensão) | 22 (imagem `node:22-slim`) |
| PostgreSQL | 16 (`postgres:16`) |
| FastAPI / Starlette | 0.162 / 1.10 |
| SQLAlchemy / Alembic | 2.1 / 1.20 |
| Pydantic | 2.14 |
| psycopg | 3.3 |
| cryptography / PyJWT | 50.0 / 2.15 |
| Next.js / React | ^16.4 / ^19.3 |
| Tailwind / TypeScript / Vitest | ^4.3 / ^7.0 / ^5.0 |
| Motor de detecção / versão da pontuação | 2.0 / `2026-11-d` |
| Migração mais recente do banco | 0021 (palavras-chave) |

**Aviso:** as versões Python vêm do que foi instalado agora, e o `pyproject.toml` só fixa mínimos (`>=`). Nada trava a versão exata; para produção, falta um arquivo de travamento (lock). Isso é uma pendência real.

## 5. Os algoritmos (sem mágica: regras, dicionários e matemática simples)
**Não há modelo de aprendizado de máquina treinado.** O NER opcional (Presidio + spaCy) vem desligado.

1. **Detectores determinísticos** (`detectors/`): padrões (regex) por tema (segredos, dados pessoais, infraestrutura, código, injection, comandos de agente, arquivos, negócio) mais **validadores matemáticos**, para não alertar à toa:
   - CPF e CNPJ (dígitos verificadores), cartão (algoritmo de Luhn), IBAN, ABA, **entropia** de Shannon para reconhecer cara de segredo.
2. **Declarações em linguagem natural** (`declared.py`): substantivo (token, senha, agência...) + conector ("é", "is", "es", ":") + valor com forma de segredo. Tolera erro de digitação, abreviação e pt/en/es. É regra sobre dicionário, não IA.
3. **Degraus de certeza**: formato conhecido (0,95+) > declaração com valor forte (0,85) > declaração com valor simples (0,55 a 0,65, moderado) > menção sem valor (nada). Placeholders (`COLE_O_TOKEN`) e variáveis são ignorados.
4. **Pontuação** (`scoring.py`), cada passo vira um "motivo" visível:
   - cada categoria contribui `peso × confiança`; a maior vale inteira e as demais valem **30%** (`SECONDARY_FACTOR`);
   - +10 se é ação de agente, +10 se conta pessoal;
   - **correlação**: combinações (ex.: credencial + destino externo) somam bônus, com teto de 25;
   - **piso de credencial**: segredo com confiança ≥ 0,9 garante no mínimo 75; ≥ 0,8, 70;
   - código compartilhado garante um piso pelo volume: até 19 linhas 15, 20 a 99 linhas 28, 100 ou mais 40;
   - limite 100. Faixas: **0-24 baixo, 25-49 médio, 50-69 alto, 70-100 crítico**.
   - O cliente pode ajustar o peso de cada categoria (pesos por empresa).
5. **Mascaramento**: trechos sensíveis viram `AKIA****` antes de gravar. Mascarar também repete a todas as ocorrências do mesmo valor.
6. **Palavras-chave** (`app/keywords`): normaliza (minúsculas, sem acento), procura o termo (ou palavra inteira); score escolhido substitui o calculado, e o motivo registra os dois.
7. **Alertas** (`alerts.py`): regras de severidade, injection, volume por usuário/hora, ação de agente fora do padrão (compara com 14 dias de histórico) e palavra-chave. **Deduplicação** por chave (regra, usuário, janela): o mesmo alerta só incrementa um contador e notifica uma vez.
8. **Políticas**: escopo (empresa, departamento, ferramenta, grupo) + exceções com validade. Em modo passivo, a ação indicada fica em `would_decide`; a decisão devolvida é sempre `allow`.

## 6. Segurança e privacidade (argumentos de venda que o código sustenta)
- Guarda **texto já mascarado**. O original só se a empresa ativar, **cifrado** (Fernet, chave por empresa derivada com HKDF-SHA256 e protegida por chave mestra).
- Chaves de API: só o **hash SHA-256** fica no banco.
- Console: login OIDC (tokens RS256/ES256 verificados por JWKS).
- Isolamento entre clientes: RLS no PostgreSQL, com testes de isolamento.
- Licenças: assinatura **Ed25519**.
- Nenhum conteúdo vai a LLM externo.

## 7. O que NÃO prometer (honestidade técnica)
- Tudo foi medido com **dados sintéticos**; nada foi validado com prompts reais de uma empresa. Taxas de acerto e de falso positivo reais são desconhecidas.
- Cada integração tem um status: **REAL, PARCIAL ou EXPERIMENTAL**. Ex.: ChatGPT e Gemini na web são PARCIAL (leitura da página, sem API documentada).
- Não captura de forma oculta: a coleta é limitada ao que o administrador configura e avisa o usuário.
- Não bloqueia. Se o cliente exigir bloqueio, é uma decisão de produto que contradiz a atual.
- Fora do escopo agora: agente de desktop, proxy de rede, cobrança automática, SSO completo, ML treinado.

## 8. Onde mexer (para programar)
| Quero... | Mexa em |
|---|---|
| Detectar algo novo | `packages/detection/.../detectors/` + teste em `packages/detection/tests` |
| Mudar peso ou faixa | `scoring.py` e a taxonomia (`packages/taxonomy/taxonomy.yaml`) |
| Nova rota da API | `apps/api/app/routers/` e registrar no teste de segurança (`tests/test_security.py`) |
| Nova tabela | modelo em `app/models.py` + migração em `alembic/versions` com RLS |
| Nova tela | `apps/web/app/(app)/` + item em `components/Shell.tsx` |
| Nova IA monitorada | adaptador em `packages/adapters` (o motor não muda) |

Regras de trabalho: passos pequenos, teste antes de dizer que terminou, e cada decisão em uma linha de `docs/decisoes.md` (contexto, escolha, alternativas).

Rodar tudo: `make up` (Docker) e `make test`.
