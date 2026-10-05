---

description: "Lista de tarefas: Agente Roteador e Agente de Suporte com Base de Conhecimento"
---

# Tasks: Agente Roteador e Agente de Suporte com Base de Conhecimento

**Input**: documentos de design em `specs/001-router-support-agent/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: INCLUÍDOS. A constituição (princípios V e VI) exige testes adversariais e de guardrails escritos
antes da implementação, cobertura de 80% e 100% em `core/guardrails`, e teste de isolamento com 2 tenants.

**Organization**: tarefas agrupadas por user story. Todos os caminhos são relativos a `plantao-ai/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivos diferentes, sem dependência pendente)
- **[Story]**: US1 a US5, conforme [spec.md](spec.md)
- Comando Python: `& ".venv\Scripts\python.exe" -m ...`

## Prioridades e MVP

US1, US2 e US3 são todas P1. O MVP entregável é **US1 + US2 + US3 juntas**: sem os guardrails e o handoff
(US3) o fluxo de US1 enviaria respostas sem a verificação exigida pela constituição (princípio V). Não coloque
o fluxo em contato com cliente real antes de concluir US3.

US4 (ingestão) é independente de US1 a US3 no código, mas as validações ponta a ponta de US1 precisam de
documentos carregados. Os testes automatizados de US1 usam fixtures com embeddings falsos e não dependem de US4.

---

## Phase 1: Setup (Fundação de qualidade FQ-1 a FQ-6)

**Purpose**: ferramentas e gates exigidos pela constituição, ainda inexistentes no Sprint 1.

- [X] T001 Criar `pyproject.toml` com ruff, mypy estrito para `core`, `agents` e `db`, pytest-asyncio (modo auto), coverage com `fail_under = 80` e marcadores `integration`, `adversarial` (FQ-1)
- [X] T002 Atualizar `requirements.txt` com `arq`, `cryptography`, `pypdf`, `langchain-text-splitters`, e `requirements-dev.txt` com `pytest-asyncio`, `pytest-cov`, `mypy`, `import-linter`, `pip-audit`, `pip-tools`, `pre-commit`, `fakeredis`, `ruff`
- [X] T003 Gerar `requirements.lock` com `pip-compile` e desinstalar do `.venv` o pacote pip `speckit` instalado por engano (R-14; depende de T002)
- [X] T004 [P] Criar `.importlinter` com 4 contratos: camadas `apps > agents > core > db`; `core` proibido de importar `agents`, `apps` e `integrations`; `agents` proibido de importar `apps`; `agents.router` e `agents.support` independentes entre si (FQ-2)
- [X] T005 [P] Criar `.pre-commit-config.yaml` com ruff, mypy e gitleaks (FQ-3)
- [X] T006 [P] Criar `.github/workflows/ci.yml` com ruff, mypy, `lint_imports`, pytest com cobertura (serviços Postgres pgvector e Redis), pip-audit e gitleaks (FQ-4). Se o repositório git tiver raiz acima de `plantao-ai/`, ajustar `working-directory`
- [X] T007 [P] Atualizar `.env.example` com `OPENROUTER_API_KEY`, `DATABASE_URL`, `DATABASE_ADMIN_URL`, `REDIS_URL`, `PILOT_TENANT_ID`, `WHATSAPP_WEBHOOK_SECRET`, `PII_ENCRYPTION_KEY`, `PII_HASH_KEY`, `RATE_LIMIT_MSGS_PER_MIN`, `HANDOFF_TTL_MINUTES`, sem valores
- [X] T008 [P] Criar `docs/adr/0001-orquestrador-em-agents.md` e `docs/adr/0002-fila-arq.md` (FQ-6)
- [X] T009 [P] Adicionar `node_modules/` e `.datacode/` (se não for versionado) ao `.gitignore`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: segurança, banco com RLS, camada de LLM e estrutura de módulos usados por todas as stories.

**CRITICAL**: nenhuma user story começa antes do fim desta fase.

### Segurança e configuração

- [X] T010 [P] Escrever teste `tests/unit/test_crypto.py`: round-trip Fernet, HMAC determinístico, chaves diferentes geram hashes diferentes
- [X] T011 [P] Escrever teste `tests/unit/test_pii.py`: máscara de telefone e nome em strings e dicts de log
- [X] T012 [P] Implementar `core/security/crypto.py` (Fernet `encrypt`/`decrypt` e HMAC-SHA256 `hash_contato`) (R-08)
- [X] T013 [P] Implementar `core/security/pii.py` (`mascarar_telefone`, `mascarar_texto`) (FR-022)
- [X] T014 Estender `core/config.py` com os novos settings de T007 e valores padrão `HANDOFF_TTL_MINUTES=60` e `RATE_LIMIT_MSGS_PER_MIN=60`; falhar na inicialização se `PII_*` ou `WHATSAPP_WEBHOOK_SECRET` estiverem ausentes

### Banco, migrações e RLS

- [X] T015 Inicializar Alembic em `db/migrations/` (`alembic.ini`, `env.py` usando `DATABASE_ADMIN_URL`, suporte a async)
- [X] T016 Criar migração `db/migrations/versions/0001_baseline.py` reproduzindo o schema do Sprint 1, com `downgrade` (FQ-5)
- [X] T017 Atualizar `db/models.py` conforme [data-model.md](data-model.md): `tenant_config` (+`palavras_gatilho`, +`router_confidence_threshold` padrão 0,6, +`min_similarity` padrão 0,30), `conversations` (remove `contato_id`; +`contato_hash` string(64), +`contato_enc` text, +`ultima_atividade_em`, +`handoff_em`), `messages` (+`tenant_id`, +`tipo`, +`external_id` string(128) null, +`intencao`, +`intencao_confianca`, +`intencoes_secundarias`, +`status_envio`, +`responde_a`), `handoff_log` (+`tenant_id`, +`message_id`), `tenant_knowledge` (+`documento_id` FK `ON DELETE CASCADE`, +`chunk_indice`, `embedding` vector(1536)), e novos modelos `KnowledgeDocument` e `LLMCall`
- [X] T018 Criar migração `0002_sprint2.py` aplicando T017 com `UNIQUE (tenant_id, external_id) WHERE external_id IS NOT NULL`, `UNIQUE (responde_a) WHERE responde_a IS NOT NULL`, `UNIQUE (tenant_id, nome_origem)` em `knowledge_documents`, índice `(tenant_id, canal, contato_hash, ultima_atividade_em DESC)` e `downgrade` (depende de T016, T017)
- [X] T019 Criar migração `0003_rls.py`: papel `plantao_app` sem superusuário, `GRANT` mínimos, `ENABLE` e `FORCE ROW LEVEL SECURITY` com política por `tenant_id = current_setting('app.tenant_id')::uuid` em todas as tabelas (em `tenants`: `id = ...`), índice HNSW `vector_cosine_ops` em `tenant_knowledge.embedding`, e `downgrade` (R-09; depende de T018)
- [X] T020 [P] Escrever `tests/integration/test_migrations.py`: `upgrade head`, `downgrade base`, `upgrade head` sem erro
- [X] T021 Implementar `tenant_session(tenant_id)` em `db/session.py` com `SET LOCAL app.tenant_id` por transação; sem tenant, consultas retornam zero linhas
- [X] T022 [P] Escrever `tests/integration/test_isolamento_tenants.py`: dois tenants; o tenant B não lê `conversations`, `messages`, `tenant_knowledge`, `llm_calls` nem `handoff_log` do A, usando o papel `plantao_app` (princípio III, FR-021)

### Portas e camada de LLM

- [X] T023 [P] Criar `core/ports/channel.py` com `Protocol MessageChannel` (`send_text`) e `ChannelError`
- [X] T024 [P] Criar `core/llm/ports.py` com `LLMClient` (`complete_json`, `embed`), `LLMResult`, `EmbedResult` e `LLMError` conforme [contracts/llm-contracts.md](contracts/llm-contracts.md)
- [X] T025 [P] Criar `core/llm/pricing.py` com tabela estática de custo por modelo, usada quando o gateway não devolve custo
- [X] T026 [P] Escrever `tests/unit/test_openrouter.py` com `httpx.MockTransport`: sucesso, timeout 15 s com 1 retry, 5xx, `LLMError`, e uma linha em `llm_calls` por chamada inclusive falha (R-12)
- [X] T027 Implementar `core/llm/openrouter.py` (`OpenRouterClient`: chat com JSON e embeddings `openai/text-embedding-3-small`, registro em `llm_calls` com modelo, tokens, custo, latência, `sucesso` e `erro` sem conteúdo do cliente) (R-01; depende de T024, T025)
- [X] T028 [P] Criar `tests/fakes/llm.py` (`FakeLLMClient` roteirizado) e `tests/fakes/channel.py` (`FakeChannel`)

### Estrutura de módulos

- [X] T029 Mover `core/orchestrator/` para `agents/orchestrator/` com `git mv`, corrigir imports e rodar `lint_imports` (ADR-0001; depende de T004)
- [X] T030 Criar `db/repositories.py`: localizar ou criar conversa por `(tenant_id, canal, contato_hash)` reutilizando a conversa com `ultima_atividade_em` dentro de 24 h (R-04), inserir mensagem com checagem de duplicata por `(tenant_id, external_id)`, carregar histórico recente
- [X] T031 [P] Criar `core/handoff/service.py` e `core/handoff/textos.py`: textos fixos de [contracts/llm-contracts.md](contracts/llm-contracts.md), `registrar_handoff` (grava `handoff_log` com `motivo` padronizado, `confianca_no_momento`, `message_id`; marca conversa como `handoff` e `handoff_em`)
- [X] T032 Criar `tests/conftest.py`: engine de teste com o Postgres do docker-compose, fixtures de dois tenants, sessão por tenant, `FakeLLMClient`, `FakeChannel`, `fakeredis`
- [X] T033 [P] Criar `apps/api/deps.py` com injeção de sessão por tenant (`PILOT_TENANT_ID`), `LLMClient`, `MessageChannel` e pool ARQ

**Checkpoint**: banco com RLS, camada de LLM, PII e módulos prontos. Stories podem começar.

---

## Phase 3: User Story 1 - Cliente final tira dúvida e recebe resposta correta (Priority: P1) MVP

**Goal**: mensagem de WhatsApp com dúvida gera resposta fundamentada nos documentos, enviada pelo canal, sem o webhook esperar o LLM.

**Independent Test**: com trechos do piloto inseridos por fixture, enviar o payload via webhook, processar o job e verificar uma única resposta correta no `FakeChannel`, e que a pergunta de seguimento usa o histórico ([quickstart.md](quickstart.md) cenários 1, 2 e 7).

### Tests for User Story 1 (escrever primeiro; devem FALHAR)

- [X] T034 [P] [US1] Teste de contrato `tests/contract/test_whatsapp_channel.py`: `parse_inbound` (texto, texto estendido, áudio, imagem, `fromMe`, sem `id`) e `send_text` (2xx, 4xx, timeout)
- [X] T035 [P] [US1] Teste de contrato `tests/contract/test_webhook.py`: 401 sem token e com token errado, 200 `queued`, `duplicate`, `ignored`, `rate_limited`, 422 e resposta em menos de 500 ms sem chamar LLM (FR-015, FR-016)
- [X] T036 [P] [US1] Teste unitário `tests/integration/test_retrieve.py`: `top_k=4`, descarte abaixo de `min_similarity`, filtro por tenant, base vazia devolve lista vazia (R-07)
- [X] T037 [P] [US1] Teste unitário `tests/unit/test_support_agent.py` com `FakeLLMClient`: resposta com trechos válidos, `responde=false`, JSON inválido com 1 retry, `trechos_usados` fora do conjunto fornecido invalida a resposta, nenhuma chamada ao LLM quando não há trechos, conteúdo do cliente e do trecho delimitado como dado (FR-005, FR-006, FR-013)
- [X] T038 [US1] Teste de integração `tests/integration/test_pipeline.py`: webhook, job e `FakeChannel` com resposta correta; pergunta de seguimento usa histórico (FR-010); mesma mensagem 2 vezes gera exatamente 1 resposta (SC-008)

### Implementation for User Story 1

- [X] T039 [P] [US1] Implementar `parse_inbound` e `send_text` em `integrations/whatsapp/client.py` (implementa `MessageChannel`; `tipo` `texto` ou `nao_texto`; `ChannelError` em falha) conforme [contracts/whatsapp-webhook.md](contracts/whatsapp-webhook.md)
- [X] T040 [P] [US1] Implementar `core/rag/retrieve.py`: embedding da pergunta, busca por similaridade cosseno filtrada por tenant, `top_k=4`, `min_similarity` do `tenant_config`
- [X] T041 [P] [US1] Criar `agents/support/schemas.py` (`responde`, `confianca`, `resposta` até 600 caracteres, `trechos_usados`)
- [X] T042 [US1] Implementar `agents/support/prompts/` e `agents/support/agent.py`: prompt com delimitadores `<mensagem_cliente>` e `<trecho id>`, saída JSON validada, 1 retry em JSON inválido, `confianca = min(LLM, f(similaridade))` (R-07, R-10, R-11; depende de T041)
- [X] T043 [P] [US1] Criar `apps/api/ratelimit.py`: limite por tenant em Redis (`RATE_LIMIT_MSGS_PER_MIN`)
- [X] T044 [US1] Reescrever `apps/api/webhooks/whatsapp.py`: validar `X-Webhook-Token` em tempo constante, parse, `contato_hash` e `contato_enc`, persistir mensagem `lead`, tratar duplicata, enfileirar só `message_id` (nunca o telefone), manter `GET` de verificação Meta (depende de T030, T039, T043)
- [X] T045 [US1] Criar `agents/orchestrator/state.py` (estado pydantic) e `agents/orchestrator/graph.py` com caminho mínimo `suporte -> envio`
- [X] T046 [US1] Implementar `processar_mensagem(message_id)` em `apps/worker/jobs.py`: carrega mensagem e histórico por `tenant_session`, executa o grafo, grava `responde_a` e `status_envio`, envia pelo canal (depende de T040, T042, T045)
- [X] T047 [US1] Criar `apps/worker/settings.py` (`WorkerSettings` do ARQ com `processar_mensagem`, pool Redis, `max_tries`)
- [X] T048 [US1] Ajustar `apps/api/main.py` para criar e fechar o pool ARQ no lifespan e registrar o router do webhook

**Checkpoint**: US1 funcional e testável sozinha (sem roteador e sem guardrails completos).

---

## Phase 4: User Story 2 - Sistema classifica a intenção de cada mensagem (Priority: P1)

**Goal**: toda mensagem recebe intenção e confiança; só "suporte" tem agente, as demais seguem para caminho seguro.

**Independent Test**: dataset rotulado de 50 mensagens com `FakeLLMClient` e depois com LLM real via `run_evals`; verificar intenção, caminho e registro ([quickstart.md](quickstart.md) cenário 5).

### Tests for User Story 2 (escrever primeiro; devem FALHAR)

- [X] T049 [P] [US2] Teste unitário `tests/unit/test_router_agent.py`: JSON válido, JSON inválido com retry, `confianca < router_confidence_threshold` trata como `suporte` (FR-002), intenção fora do enum, `intencoes_secundarias` sem repetir a principal
- [X] T050 [P] [US2] Criar dataset `tests/evals/intencoes.yaml` com 50 mensagens rotuladas (venda, suporte, agendamento, cobrança, outro; inclui intenção mista)
- [X] T051 [US2] Teste de integração `tests/integration/test_pipeline.py`: suporte vai ao agente; agendamento, venda e cobrança geram handoff `intencao_sem_agente:<intencao>` com intenção gravada (FR-004); intenção mista trata a dúvida e registra a secundária

### Implementation for User Story 2

- [X] T052 [P] [US2] Criar `agents/router/schemas.py` com enum de intenções e validação 0.0 a 1.0
- [X] T053 [US2] Implementar `agents/router/prompts/` e `agents/router/agent.py` com modelo `model_cheap`, saída JSON e histórico curto (R-05; depende de T052)
- [X] T054 [US2] Adicionar o nó `roteador` em `agents/orchestrator/graph.py` com arestas condicionais (limiar, `suporte`, outras intenções para `handoff`)
- [X] T055 [US2] Persistir `intencao`, `intencao_confianca` e `intencoes_secundarias` na mensagem do `lead` em `apps/worker/jobs.py` e `db/repositories.py`

**Checkpoint**: US1 e US2 funcionam juntas.

---

## Phase 5: User Story 3 - Pergunta sem resposta na base vai para atendente humano (Priority: P1)

**Goal**: nada é enviado ao cliente sem guardrails; qualquer dúvida, falha ou gatilho vira handoff com motivo registrado.

**Independent Test**: 20 perguntas fora da base e 20 casos adversariais geram handoff e nenhuma informação inventada ([quickstart.md](quickstart.md) cenários 3, 4, 6 e 9).

### Tests for User Story 3 (escrever primeiro; devem FALHAR; cobertura 100% em `core/guardrails`)

- [X] T056 [P] [US3] Criar `tests/unit/test_guardrails_entrada.py` (substitui `tests/test_guardrails.py`): palavra-gatilho com variação de caixa e acento, mensagem vazia, só emoji, não texto
- [X] T057 [P] [US3] Criar `tests/unit/test_guardrails_saida.py`: ordem fixa (confiança mínima, tópico proibido, desconto acima do limite, valor não fundamentado) e motivo da primeira regra que dispara
- [X] T058 [P] [US3] Criar `tests/adversarial/test_adversarial.py` com 20 casos: pedido para ignorar regras, instrução oculta em trecho de documento, tópico proibido, gatilho, desconto acima do limite, valor monetário inventado (SC-003)
- [X] T059 [P] [US3] Teste de integração `tests/integration/test_pipeline.py`: `sem_resposta_na_base`, `palavra_gatilho:<termo>`, `nao_texto`, `confianca_abaixo_do_minimo`, `falha_llm`, falha do canal grava `status_envio=falha`, zero chamadas de LLM nos casos determinísticos, e TTL de handoff (conversa em `handoff` não recebe resposta automática até `HANDOFF_TTL_MINUTES`) (FR-007, FR-008, FR-014, FR-020)

### Implementation for User Story 3

- [X] T060 [P] [US3] Implementar `core/guardrails/input_checks.py` (`checar_entrada`: gatilhos, vazio, não texto) como função pura
- [X] T061 [P] [US3] Implementar `core/guardrails/output_checks.py` (`checar_saida`: confiança mínima, tópico proibido, desconto acima do limite, valores monetários presentes nos trechos) como função pura (R-10)
- [X] T062 [US3] Remover `core/guardrails/checks.py` e `tests/test_guardrails.py` após migrar o conteúdo útil (depende de T056, T057, T060, T061)
- [X] T063 [US3] Completar `agents/orchestrator/graph.py` com nós `entrada`, `guardrails_saida` e `handoff` e arestas conforme o fluxo de [plan.md](plan.md); `handoff` usa `core/handoff` e os textos fixos
- [X] T064 [US3] Aplicar o TTL de handoff em `apps/worker/jobs.py`: mensagem em conversa `handoff` é só persistida; após o TTL sem atividade humana a conversa volta a `aberta` (R-04)
- [X] T065 [US3] Degradar falhas em `apps/worker/jobs.py`: `LLMError` e erro de embedding viram handoff (`falha_llm`, `falha_embedding`); `ChannelError` grava `status_envio=falha` e registra a falha (FR-020)

**Checkpoint**: fluxo seguro completo. MVP (US1 + US2 + US3) pronto para a validação do quickstart.

---

## Phase 6: User Story 4 - Operador carrega e atualiza os documentos da empresa piloto (Priority: P2)

**Goal**: operador carrega, lista, recarrega e remove documentos pelo CLI; a recarga substitui a versão anterior de forma atômica.

**Independent Test**: carregar um documento, perguntar algo contido nele, alterá-lo, recarregar e ver `versao=2` e resposta atualizada ([quickstart.md](quickstart.md) passo 2).

### Tests for User Story 4 (escrever primeiro; devem FALHAR)

- [X] T066 [P] [US4] Teste unitário `tests/unit/test_chunking.py`: tamanho 800 com sobreposição 100, texto vazio, texto curto (R-06)
- [X] T067 [P] [US4] Teste `tests/integration/test_ingest.py`: documento novo, mesmo `content_hash` devolve `inalterado`, conteúdo diferente substitui trechos e incrementa `versao`, PDF sem texto devolve `sem_texto`, extensão `nao_suportado`, arquivo acima de 5 MB devolve `arquivo_grande`, falha de embedding mantém a versão anterior (atomicidade)
- [X] T068 [P] [US4] Teste `tests/integration/test_ingest_cli.py`: saída por documento de [contracts/knowledge-cli.md](contracts/knowledge-cli.md), código de saída 0 e 1, `list`, `remove --yes`
- [X] T069 [P] [US4] Criar documentos de exemplo da clínica piloto em `tests/evals/docs_piloto/` (FAQ, preços, políticas, horários) sem dados pessoais

### Implementation for User Story 4

- [X] T070 [P] [US4] Implementar `core/rag/chunking.py` com `RecursiveCharacterTextSplitter` (800/100) e extração de PDF com `pypdf`
- [X] T071 [US4] Implementar `core/rag/ingest.py`: hash, versionamento, substituição atômica em uma transação, embeddings em lote via `core/llm`, contagem de trechos e custo (depende de T070)
- [X] T072 [US4] Implementar `scripts/ingest_docs.py` com subcomandos `load`, `list` e `remove`, tenant fixo `PILOT_TENANT_ID` (depende de T071)
- [X] T073 [P] [US4] Atualizar `scripts/seed_tenant.py` com a config completa do piloto (`palavras_gatilho`, `router_confidence_threshold`, `min_similarity`, tópicos proibidos, limite de desconto, `confianca_minima_handoff`) e impressão do id para `PILOT_TENANT_ID`

**Checkpoint**: operador consegue preparar a base do piloto em menos de 10 minutos (SC-010).

---

## Phase 7: User Story 5 - Operador acompanha uso e custo por conversa (Priority: P2)

**Goal**: toda mensagem processada tem registro de uso e, quando há repasse, de motivo e confiança; logs estruturados sem PII.

**Independent Test**: processar 10 mensagens e consultar `llm_calls` e `handoff_log` ([quickstart.md](quickstart.md) passo 4, consultas SQL).

### Tests for User Story 5 (escrever primeiro; devem FALHAR)

- [X] T074 [P] [US5] Teste `tests/integration/test_registro_uso.py`: cada mensagem processada tem linha em `llm_calls` com modelo, tokens, `custo_usd` e `latencia_ms`; cada handoff tem `motivo`, `confianca_no_momento`, `message_id` (FR-017, FR-018, SC-007)
- [X] T075 [P] [US5] Teste `tests/unit/test_logging.py`: saída JSON com `correlation_id`, `tenant_id`, `conversation_id`; telefone e nome mascarados (FR-022)

### Implementation for User Story 5

- [X] T076 [US5] Reescrever `core/observability/logging.py`: formatador JSON, contexto por `contextvars`, filtro de máscara usando `core/security/pii.py` (R-13)
- [X] T077 [US5] Gerar e propagar `correlation_id` no webhook (`apps/api/main.py`) e no job (`apps/worker/jobs.py`)
- [X] T078 [US5] Garantir em `apps/worker/jobs.py` que `llm_calls` e `handoff_log` ficam associados a `conversation_id` e `message_id` em todos os caminhos, incluindo falhas (depende de T055, T065)

**Checkpoint**: custo e motivos de handoff auditáveis por mensagem.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: avaliação com LLM real, calibração e fechamento da definição de pronto.

- [X] T079 [P] Criar os 9 payloads de cenário em `tests/evals/payloads/` (`horario_sabado`, `seguimento_domingo`, `convenio_x`, `procon`, `quero_agendar`, `audio`, `ignore_regras` e duplicata) conforme [quickstart.md](quickstart.md)
- [X] T080 [P] Criar datasets em `tests/evals/`: `perguntas_com_resposta.yaml` (30), `perguntas_sem_resposta.yaml` (20), `adversariais.yaml` (20)
- [X] T081 Implementar `scripts/run_evals.py` (`--suite todas`) com tabela de metas SC-001 a SC-006 e SC-009; código de saída 1 se alguma falhar (depende de T050, T080)
- [X] T082 Rodar a pipeline de qualidade (`pytest --cov`, `ruff`, `mypy`, `lint_imports`) e fechar lacunas de cobertura: 80% em `core` e `agents`, 100% em `core/guardrails`
- [ ] T083 Calibrar `min_similarity` e `confianca_minima_handoff` em `tenant_config` com `run_evals` (R-07). Não relaxar guardrails para atingir metas. **Pendente: exige OPENROUTER_API_KEY real**
- [ ] T084 Executar a validação completa de [quickstart.md](quickstart.md) (cenários 1 a 9 e verificação de ausência de telefone em texto puro no banco, fila e logs). **Pendente: exige OpenRouter e Evolution API reais**
- [X] T085 [P] Atualizar `README.md` com setup, migrações, ingestão e execução de API e worker, e criar `docs/SPRINT_2_RESULTADOS.md` com as métricas do `run_evals`
- [X] T086 [P] Remover o comentário Sync Impact Report de `.specify/memory/constitution.md` e registrar a decisão sobre propagar os gates aos templates
- [ ] T087 Executar `pip-audit` e `gitleaks` no repositório inteiro e corrigir achados. **Parcial: `pip-audit` limpo; `gitleaks` não instalado localmente (roda no CI/pre-commit)**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sem dependências; T004 precisa existir antes de T029.
- **Foundational (Phase 2)**: depende de Setup; bloqueia todas as stories.
- **US1 (Phase 3)**: depende de Foundational.
- **US2 (Phase 4)**: depende de Foundational e do `graph.py` de US1 (T045).
- **US3 (Phase 5)**: depende de Foundational e do `jobs.py` e `graph.py` de US1 (T045, T046); integra com US2.
- **US4 (Phase 6)**: depende apenas de Foundational; pode rodar em paralelo com US1 a US3.
- **US5 (Phase 7)**: depende de Foundational (cliente LLM) e dos jobs de US1; T078 depende de T055 e T065.
- **Polish (Phase 8)**: depende das stories desejadas; T081 depende de T050 e T080.

### Dentro de cada story

- Testes primeiro e falhando; depois schemas, agentes e serviços; depois endpoints e integração.
- US1, US2 e US3 editam `graph.py` e `jobs.py`: executar nessa ordem, sem paralelismo entre elas.

### Dependências críticas entre tarefas

- T018 depende de T016 e T017; T019 depende de T018; T021 e T022 dependem de T019.
- T027 depende de T024, T025 e T019 (`llm_calls`).
- T044 depende de T030, T039 e T043; T046 depende de T040, T042 e T045.
- T062 só após T056, T057, T060 e T061.

## Parallel Opportunities

- Phase 1: T004 a T009 em paralelo após T001.
- Phase 2: T010 a T013 (segurança) em paralelo com T023 a T026 e T028; migrações (T015 a T019) em sequência.
- US1: T034 a T037 em paralelo; depois T039, T040, T041 e T043 em paralelo.
- US3: T056 a T059 em paralelo; T060 e T061 em paralelo.
- US4 inteira pode ser feita por outra frente ao lado de US1 a US3.

### Exemplo: User Story 1

```text
Tarefas em paralelo (testes):
  T034 tests/contract/test_whatsapp_channel.py
  T035 tests/contract/test_webhook.py
  T036 tests/integration/test_retrieve.py
  T037 tests/unit/test_support_agent.py

Tarefas em paralelo (implementação base):
  T039 integrations/whatsapp/client.py
  T040 core/rag/retrieve.py
  T041 agents/support/schemas.py
  T043 apps/api/ratelimit.py
```

## Implementation Strategy

### MVP first (US1 + US2 + US3)

1. Phase 1 e Phase 2 completas.
2. US1, depois US2, depois US3, validando cada checkpoint com os testes da story.
3. Em paralelo ou logo depois, US4 para carregar documentos reais do piloto.
4. PARAR e validar com [quickstart.md](quickstart.md) cenários 1 a 9 antes de qualquer contato com cliente.

### Entrega incremental

1. Foundational pronta: banco, RLS, LLM e PII testados.
2. US1: responde com base nos documentos (apenas ambiente de teste).
3. US2: roteamento e caminho seguro.
4. US3: guardrails e handoff completos (MVP liberável para o beta).
5. US4 e US5: operação e auditoria.
6. Polish: `run_evals`, calibração e fechamento da definição de pronto.

## Notes

- [P] significa arquivos diferentes e sem dependência pendente.
- Confirmar que cada teste falha antes de implementar.
- Fazer commit a cada tarefa ou grupo lógico.
- Nenhum telefone em texto puro em banco, fila ou logs em nenhum momento (FR-022, princípio IV).
- Orçamento e alerta de custo por tenant ficam fora do escopo (Sprint 6, ver Complexity Tracking em [plan.md](plan.md)).
