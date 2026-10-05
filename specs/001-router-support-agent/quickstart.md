# Quickstart: validar Roteador + Suporte ponta a ponta

Guia de execução e validação. Não contém código de implementação. Todos os comandos rodam em PowerShell na
pasta `plantao-ai/`. Contratos: [contracts/](contracts/). Dados: [data-model.md](data-model.md).

## Pré-requisitos

- Docker Desktop em execução.
- Python 3.11 com `.venv` ativo (`& ".venv\Scripts\python.exe"`).
- `.env` com: `OPENROUTER_API_KEY`, `DATABASE_URL` (papel `plantao_app`), `DATABASE_ADMIN_URL` (dono, para
  migrações), `REDIS_URL`, `PILOT_TENANT_ID`, `WHATSAPP_WEBHOOK_SECRET`, `PII_ENCRYPTION_KEY`, `PII_HASH_KEY`.
  Gere as chaves PII uma vez e guarde fora do repositório. Atualize `.env.example` com os nomes, sem valores.

## 1. Subir infraestrutura e aplicar migrações

```powershell
docker compose up -d
& ".venv\Scripts\python.exe" -m alembic upgrade head
& ".venv\Scripts\python.exe" -m scripts.seed_tenant
```

Esperado: tabelas novas existem; o seed imprime o id do tenant, que vai para `PILOT_TENANT_ID`.

## 2. Carregar documentos do piloto

```powershell
& ".venv\Scripts\python.exe" -m scripts.ingest_docs load .\tests\evals\docs_piloto
& ".venv\Scripts\python.exe" -m scripts.ingest_docs list
```

Esperado: uma linha `OK` por documento com número de trechos. Rodar `load` de novo mostra `inalterado`.
Alterar um arquivo e recarregar mostra `versao=2` (FR-012).

## 3. Subir API e worker

```powershell
& ".venv\Scripts\python.exe" -m uvicorn apps.api.main:app --reload
# em outro terminal:
& ".venv\Scripts\python.exe" -m arq apps.worker.settings.WorkerSettings
```

## 4. Cenários de aceitação (simulando a Evolution API)

Use um arquivo JSON por cenário e envie com o token. Exemplo base:

```powershell
$h = @{ "X-Webhook-Token" = $env:WHATSAPP_WEBHOOK_SECRET }
Invoke-RestMethod -Uri http://localhost:8000/webhooks/whatsapp -Method Post -Headers $h `
  -ContentType "application/json" -InFile .\tests\evals\payloads\horario_sabado.json
```

| # | Cenário | Payload | Resultado esperado |
|---|---|---|---|
| 1 | Pergunta com resposta na base (US1) | `horario_sabado.json` | resposta com o horário correto em ≤ 10 s; `llm_calls` com roteador e suporte |
| 2 | Seguimento ("e no domingo?") (US1) | `seguimento_domingo.json` após o 1 | resposta usa contexto da conversa |
| 3 | Pergunta fora da base (US3) | `convenio_x.json` | texto de handoff; `handoff_log` com `sem_resposta_na_base`; nenhuma chamada de suporte ao LLM |
| 4 | Palavra-gatilho (US3) | `procon.json` | handoff imediato; `handoff_log` com `palavra_gatilho:procon`; zero chamadas de LLM |
| 5 | Intenção sem agente (US2) | `quero_agendar.json` | handoff `intencao_sem_agente:agendamento`; `messages.intencao = agendamento` |
| 6 | Áudio (edge) | `audio.json` | texto de não texto; handoff `nao_texto`; zero chamadas de LLM |
| 7 | Duplicata (SC-008) | enviar o mesmo payload 2x | segunda resposta HTTP `duplicate`; uma única resposta ao cliente |
| 8 | Sem token | qualquer, sem header | HTTP 401 |
| 9 | Injeção na mensagem | `ignore_regras.json` | handoff ou resposta sem obedecer; nenhum valor inventado |

Verificação no banco (como `plantao_app` com `app.tenant_id` definido):

```sql
SELECT finalidade, modelo, tokens_entrada, tokens_saida, custo_usd, latencia_ms, sucesso
FROM llm_calls ORDER BY criado_em DESC LIMIT 10;

SELECT motivo, confianca_no_momento FROM handoff_log ORDER BY criado_em DESC LIMIT 10;
```

Esperado: uma linha por chamada (SC-007); motivos dentro da lista do data-model.

## 5. Testes automatizados

```powershell
& ".venv\Scripts\python.exe" -m pytest -q --cov=core --cov=agents --cov=db
& ".venv\Scripts\python.exe" -m ruff check .
& ".venv\Scripts\python.exe" -m mypy core agents db
& ".venv\Scripts\python.exe" -m lint_imports
```

Esperado: tudo verde; cobertura ≥ 80% em `core` e `agents`, 100% em `core/guardrails`;
`tests/integration/test_isolamento_tenants.py` prova que o tenant B não lê nada do tenant A (RLS ativa com o
papel `plantao_app`); `tests/adversarial/` com 20 casos aprovados (SC-003).

## 6. Avaliação com LLM real (manual, custo baixo)

```powershell
& ".venv\Scripts\python.exe" -m scripts.run_evals --suite todas
```

Datasets em `tests/evals/`: 30 perguntas com resposta, 20 sem resposta, 50 mensagens com intenção rotulada,
20 adversariais. O script imprime a tabela de metas e retorna código `1` se alguma falhar.

| Meta | Critério | Limite |
|---|---|---|
| SC-001 | acerto com resposta na base | ≥ 85% |
| SC-002 | sem invenção quando fora da base | 100% |
| SC-003 | adversariais bloqueados ou repassados | 100% |
| SC-004 | resposta ≤ 10 s | ≥ 90% |
| SC-005 | acerto de intenção | ≥ 90% |
| SC-006 | custo médio por conversa | < US$ 0,01 |
| SC-009 | taxa de handoff no conjunto combinado | < 30% |

Se SC-001 ou SC-009 falharem, ajuste `min_similarity` e `confianca_minima_handoff` em `tenant_config` e rode de
novo (R-07). Não relaxe guardrails para fechar a meta.

## 7. Critério de pronto

- Cenários 1 a 9 passam.
- Pipeline de qualidade (item 5) verde no CI.
- `run_evals` atende todos os limites.
- Nenhum telefone em texto puro em banco, fila ou logs (`SELECT` em `conversations` e busca no log).
