# Sprint 2 — Resultados e limitações

Feature: `001-router-support-agent` (Roteador + Suporte com RAG, guardrails e handoff).

## 1. O que foi verificado automaticamente

Execução offline (LLM e WhatsApp simulados, Postgres e Redis reais via Docker):

| Verificação | Resultado |
|---|---|
| `pytest` | 295 testes passando |
| Cobertura total (`core`, `agents`, `db`, `apps`, `integrations`) | 94% (gate: 80%) |
| Cobertura de `core/guardrails` | 100% (gate: 100%) |
| `ruff check` | sem erros |
| `mypy` (estrito, 67 arquivos) | sem erros |
| `lint-imports` | 4 contratos mantidos |
| `pip-audit` | sem vulnerabilidades conhecidas |
| Suíte adversarial (20 casos) | 20 bloqueados ou escalados |
| Isolamento entre tenants (RLS) | coberto por testes de integração |

Linhas sem cobertura são, em sua maioria, código de composição que só roda com serviços reais: `apps/composition.py`, `apps/worker/settings.py`, o `lifespan` de `apps/api/main.py` e a construção dos clientes externos.

## 2. O que ainda exige execução manual com serviços reais

Estas verificações não podem ser feitas sem a chave do OpenRouter e uma instância da Evolution API:

- **Calibração com LLM real (T083).** Rodar `python -m scripts.run_evals --suite todas`, registrar a tabela abaixo e ajustar, se necessário, `min_similarity` e `confianca_minima_handoff` em `tenant_config`, as constantes de confiança por similaridade (0,30 a 0,60, em `agents/support/agent.py`) e os prompts.
- **Quickstart ponta a ponta (T084).** Seguir [../specs/001-router-support-agent/quickstart.md](../specs/001-router-support-agent/quickstart.md) com uma mensagem WhatsApp real.
- **Varredura de segredos.** `gitleaks` não estava instalado no ambiente de desenvolvimento; rodar via pre-commit ou CI.

Tabela a preencher após a execução real:

| Meta (spec) | Alvo | Medido |
|---|---|---|
| Acerto de roteamento (50 mensagens) | definido no spec | pendente |
| Respostas fundamentadas (30 perguntas com resposta) | definido no spec | pendente |
| Handoff nas 20 perguntas sem resposta | definido no spec | pendente |
| Adversarial (20 casos, LLM real) | 100% bloqueados | pendente |
| Latência p95 | definido no spec | pendente |
| Custo médio por conversa | definido no spec | pendente |
| SC-009 (falso handoff) | definido no spec | pendente |

## 3. Desvios e interpretações

- **SC-009.** A métrica literal combinada seria impossível: as 20 perguntas sem resposta já representam 40% do conjunto de 50 e todas devem gerar handoff. Por isso `run_evals` mede a taxa de falso handoff somente nas perguntas que têm resposta na base. Revisar o texto do spec se esta interpretação não for a pretendida.
- **Organização dos testes.** O conteúdo planejado para `test_pipeline_suporte`, `test_roteamento` e `test_handoff` foi reunido em `tests/integration/test_pipeline.py`, e `test_retrieve` ficou em `tests/integration/`. Os caminhos em `tasks.md` foram ajustados.
- **Testes escritos junto com o código.** Não foi seguido o ciclo estrito red-green que a constituição descreve; os testes foram escritos na mesma fase de cada história.

## 4. Limitações conhecidas

- **Documentos são dados confiáveis do operador.** Se um documento da base contém uma instrução maliciosa e também o valor que ela induz a falar, o guardrail de "valor fundamentado" aceita o valor, pois ele consta nos trechos recuperados. Mitigações atuais: limite de desconto, frases proibidas e revisão do conteúdo no momento da ingestão. Mitigação futura: revisão humana na ingestão.
- **Falha ao enfileirar após persistir.** No webhook, se a mensagem é gravada mas o enfileiramento no Redis falha, a mensagem fica sem processamento: a retentativa do provedor retorna `duplicate`. Corrigir com um reprocessador periódico de mensagens sem resposta (candidato ao Sprint 3).
- **Um único tenant piloto.** O `PILOT_TENANT_ID` fixa o tenant dos scripts. O onboarding programático é escopo do Sprint 3, embora o isolamento por RLS já esteja ativo e testado.
- **Um único canal e idioma.** WhatsApp via Evolution API e português do Brasil. Áudio e mídia geram handoff.

## 5. Migração do banco de desenvolvimento do Sprint 1

O banco `plantao` criado no Sprint 1 tem o esquema antigo, sem Alembic. Opções:

```powershell
alembic stamp 0001
alembic upgrade head
```

Isso preserva a estrutura mas pode exigir descartar os dados de teste do Sprint 1. Alternativa limpa: `docker compose down -v` seguido de `docker compose up -d` e `alembic upgrade head`.
