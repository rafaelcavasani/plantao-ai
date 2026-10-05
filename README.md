# Plantão.AI — Núcleo de Agentes de IA (Agentic Ops as a Service)

> Implementação técnica da ideia detalhada em [Projeto_Empresa_Autonoma.md](../Projeto_Empresa_Autonoma.md) (seções 7 a 9) e no [Plano_de_Estudos.md](../Plano_de_Estudos.md) (Módulo 11 — Capstone).

"A equipe de IA que fica de plantão pelo seu negócio — 24 horas por dia, 7 dias por semana."

## O que é

Núcleo multi-tenant de agentes de IA que atendem clientes finais de pequenas e médias empresas via WhatsApp. No estado atual (Sprint 2, feature `001-router-support-agent`) o fluxo é:

```
WhatsApp -> webhook (FastAPI) -> fila (arq/Redis) -> worker
         -> guardrails de entrada -> Roteador -> Suporte (RAG) -> guardrails de saída
         -> resposta ao cliente OU handoff para humano
```

- **Roteador** classifica a intenção da mensagem.
- **Suporte** responde apenas com base nos documentos do tenant (RAG com pgvector), cita os trechos usados e calcula a confiança; abaixo do limiar, faz handoff.
- **Guardrails** (entrada e saída) cobrem PII, injeção de prompt, valores não fundamentados, promessas proibidas e limite de desconto.
- **Multi-tenancy** com Row-Level Security no Postgres (papel `plantao_app`, sem superusuário).
- **PII** criptografada em repouso (Fernet) e mascarada nos logs.

Especificação, plano, contratos e tarefas ficam em [specs/001-router-support-agent/](specs/001-router-support-agent/). Os princípios de engenharia estão em [.specify/memory/constitution.md](.specify/memory/constitution.md) e as decisões de arquitetura em [docs/adr/](docs/adr/).

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ (type hints, mypy estrito) |
| API | FastAPI (async) |
| Orquestração | LangGraph |
| LLM | OpenRouter (gateway) |
| Banco | PostgreSQL 16 + pgvector, SQLAlchemy 2 async, Alembic |
| Fila / cache | Redis + arq |
| WhatsApp (MVP) | Evolution API (self-hosted) |

## Camadas (verificadas por import-linter)

```
apps  >  agents  >  core  >  db
```

- `apps/` — API (webhook, health) e worker (job `processar_mensagem`).
- `agents/` — `router/`, `support/` e `orchestrator/` (grafo).
- `core/` — config, guardrails, handoff, llm, observability, ports, rag, security.
- `integrations/` — adaptadores externos (WhatsApp).
- `db/` — modelos, sessão com RLS, repositórios e migrações.
- `scripts/` — `seed_tenant`, `ingest_docs`, `run_evals`.

## Como rodar localmente

Todos os comandos a partir de `plantao-ai/`.

### 1. Infraestrutura e dependências

```powershell
docker compose up -d
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

### 2. Variáveis de ambiente

```powershell
Copy-Item .env.example .env
```

Preencha no `.env`:

| Variável | Observação |
|---|---|
| `DATABASE_URL` | Usa o papel `plantao_app` (sujeito a RLS) |
| `DATABASE_ADMIN_URL` | Superusuário, só para migrações e seed |
| `APP_DB_PASSWORD` | Senha do papel `plantao_app` criado pela migração |
| `OPENROUTER_API_KEY` | Chave do OpenRouter |
| `PII_ENCRYPTION_KEY` | Chave Fernet (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `PII_HASH_KEY` | Segredo para o hash de contatos |
| `WHATSAPP_WEBHOOK_SECRET` | Token esperado no webhook |
| `WHATSAPP_BASE_URL`, `WHATSAPP_API_KEY`, `WHATSAPP_INSTANCE` | Evolution API |
| `PILOT_TENANT_ID` | Preenchido após o seed (passo 4) |

### 3. Migrações

```powershell
alembic upgrade head
```

### 4. Tenant piloto e base de conhecimento

```powershell
python -m scripts.seed_tenant                 # imprime o PILOT_TENANT_ID; copie para o .env
python -m scripts.ingest_docs load tests\evals\docs_piloto
python -m scripts.ingest_docs list
python -m scripts.ingest_docs remove faq_clinica.md --yes
```

### 5. API e worker

```powershell
uvicorn apps.api.main:app --reload
arq apps.worker.settings.WorkerSettings
```

`GET /health` responde na porta 8000. O webhook é `POST /webhooks/whatsapp` com o token configurado.

O passo a passo completo, incluindo o teste com a Evolution API, está em [specs/001-router-support-agent/quickstart.md](specs/001-router-support-agent/quickstart.md).

## Qualidade

```powershell
ruff check . ; ruff format --check .
mypy
lint-imports
pytest --cov
pip-audit
```

- Os testes de integração exigem o Postgres e o Redis do `docker compose`. O banco `plantao_test` é recriado a cada sessão.
- Gate de cobertura: 80% no total e 100% em `core/guardrails` (`coverage report --include="core/guardrails/*" --fail-under=100`).
- Suíte adversarial: `pytest tests/adversarial`.
- Atalhos: `make help` lista os comandos do [Makefile](Makefile) (`make check` roda todos os gates).
- Hooks: `pre-commit install -c plantao-ai/.pre-commit-config.yaml` (a partir da raiz do repositório). O CI está em `.github/workflows/ci.yml` na raiz.

## Avaliação com LLM real

As suítes em `tests/evals/` medem as metas do spec (acerto de roteamento, groundedness, handoff, adversarial, latência e custo). Exigem `OPENROUTER_API_KEY` e consomem créditos:

```powershell
python -m scripts.run_evals --suite todas
```

Resultados e limitações do Sprint 2: [docs/SPRINT_2_RESULTADOS.md](docs/SPRINT_2_RESULTADOS.md).

## Roadmap

| Sprint | Entrega |
|:---:|---|
| 1 | Fundação: repositório, Postgres + pgvector, FastAPI, webhook WhatsApp (eco) |
| 2 | Agente Roteador + Agente de Suporte com RAG, guardrails, handoff (1 tenant piloto) |
| 3 | Onboarding programático de tenants |
| 4 | Agente Agendador (Google Calendar) |
| 5 | Agente SDR + guardrails ampliados |
| 6 | Observabilidade (LangSmith) + cobrança recorrente |

Histórico: [docs/SPRINT_1_PLAN.md](docs/SPRINT_1_PLAN.md).
