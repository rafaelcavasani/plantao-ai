# ADR-0002: Fila de processamento com ARQ sobre Redis

- Status: aceita
- Data: 2026-10-04
- Contexto da feature: [specs/001-router-support-agent](../../specs/001-router-support-agent/research.md) (R-02)

## Contexto

O requisito FR-016 exige que o webhook confirme o recebimento sem esperar o LLM. A seção 8.2 do projeto
cita Redis com RQ ou Celery. O código é assíncrono de ponta a ponta (FastAPI, SQLAlchemy async, httpx).

## Decisão

Usar `arq` (fila assíncrona sobre Redis). O webhook persiste a mensagem e enfileira o job
`processar_mensagem(tenant_id, message_id, correlation_id)`. Apenas identificadores entram na fila:
telefone e texto nunca passam pelo Redis (princípio IV).

Idempotência em três níveis: `UNIQUE (tenant_id, external_id)` no banco, `_job_id` por mensagem no ARQ e
verificação de resposta já existente (`messages.responde_a`) dentro do job.

## Alternativas rejeitadas

- RQ e Celery: síncronos, exigiriam ponte para código async.
- `BackgroundTasks` do FastAPI: perde jobs em reinício e não tem retry.
- Processar no request: viola FR-016.

## Consequências

- Nova dependência (`arq`), compatível com a versão de `redis` fixada no lockfile.
- Em falha do worker depois de gravar a resposta e antes de enviá-la, o retry do ARQ não reenvia
  (resposta já existe). A mensagem fica com `status_envio = pendente` e é visível para auditoria. O
  sistema prefere não responder a responder duas vezes.
