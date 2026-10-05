---

description: "Lista de tarefas: Multi-tenancy real"
---

# Tasks: Multi-tenancy real

**Input**: documentos de design em `specs/002-multitenancy/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: INCLUÍDOS. A constituição (princípios III, V e VI) exige teste de isolamento com tenants para toda feature que
toca dados, testes adversariais escritos antes da implementação, migração reversível e cobertura de 80% (100% em
`core/guardrails`). O FR-028 da spec exige a suíte de isolamento com 3 empresas em toda alteração do código.

**Organization**: tarefas agrupadas por user story. Todos os caminhos são relativos a `plantao-ai/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivos diferentes, sem dependência pendente)
- **[Story]**: US1 a US6, conforme [spec.md](spec.md)
- Comando Python: `& ".venv\Scripts\python.exe" -m ...`
- Valores de campos citados entre aspas vêm de [data-model.md](data-model.md) e não ficam a critério da implementação

## Prioridades e MVP

US1, US2 e US3 são P1. O MVP entregável é **US1 + US2 + US3 juntas**: sem a criação repetível (US2) não há segundo
cliente, e sem a prova de isolamento (US3) a constituição (princípio III) proíbe pôr um segundo cliente em
produção. US4 e US5 (P2) são necessárias antes de cobrar (seção 8.10). US6 (P3) fecha o ciclo de vida.

US1 muda webhook, worker, canal e configuração: é a story que remove o tenant fixo. US2 a US6 são independentes entre
si no código, mas todas dependem de US1 para o fluxo completo e editam `scripts/tenants.py` e
`core/tenancy/ciclo_vida.py`, então devem ser executadas em ordem de prioridade, sem paralelismo entre as stories.

**Atenção (correção do plano)**: o plano original previa `SELECT ... FOR SHARE` em `tenants` para fechar a janela
da suspensão. Esse bloqueio exige privilégio `UPDATE` em `tenants`, que o papel `plantao_app` não tem. As tarefas usam
trava advisory do Postgres (`pg_advisory_xact_lock_shared` no worker, `pg_advisory_xact_lock` na mudança de estado),
já corrigida em [research.md](research.md) R-06.

---

## Phase 1: Setup

**Purpose**: dependência, variáveis de ambiente, decisões registradas e a confirmação que pode mudar o desenho.

- [X] T001 Mover `pyyaml` para `requirements.txt` (continua em `requirements-dev.txt`) e regenerar `requirements.lock` e `requirements-dev.lock` com `pip-compile` (research R-09)
- [X] T002 [P] Atualizar `.env.example`: remover `PILOT_TENANT_ID`, `WHATSAPP_WEBHOOK_SECRET`, `WHATSAPP_INSTANCE`, `WHATSAPP_API_KEY`, `RATE_LIMIT_MSGS_PER_MIN` e `HANDOFF_TTL_MINUTES`; manter `WHATSAPP_PROVIDER`, `WHATSAPP_BASE_URL` e `WHATSAPP_VERIFY_TOKEN`; adicionar `PURGE_DRENAGEM_SEGUNDOS=120` e um comentário explicando que as credenciais de cada empresa entram por variáveis nomeadas no arquivo de onboarding (research R-03, R-15)
- [X] T003 [P] Criar `docs/adr/0003-resolucao-por-conexao.md` (instância do payload como chave de busca, autenticação por segredo da conexão, leitura aberta em `channel_connections` como exceção do princípio III, trava advisory no lugar de `FOR SHARE`) e `docs/adr/0004-exclusao-de-dados-de-empresa.md` (drenagem, marca em `tenants`, `audit_log` sem FK)
- [ ] T004 [P] Confirmar com uma instância real da Evolution API: (a) o corpo de `messages.upsert` traz `instance`; (b) `POST /webhook/set/{instance}` aceita header customizado por instância; (c) `GET /instance/connectionState/{instance}` devolve `state` com valor `open` quando conectada. Se algum ponto falhar, aplicar a contingência de research R-02 ou R-10 **antes** de T028 e T034 e registrar o resultado no ADR 0003. **Pendente: exige Evolution API real**

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: schema, modelo padrão, validação, auditoria e cadastro de conexão usados por todas as stories.

**CRITICAL**: nenhuma user story começa antes do fim desta fase.

### Testes (escrever primeiro; devem FALHAR)

- [X] T005 [P] Escrever `tests/unit/test_config_empresa.py`: `ConfigEmpresa` aceita os valores de `CONFIG_PADRAO`; recusa `confianca_minima_handoff`, `router_confidence_threshold` e `min_similarity` fora de "entre 0 e 1"; `limite_desconto_percentual` fora de "entre 0 e 100"; `handoff_ttl_minutos` fora de "entre 1 e 1440"; `limite_mensagens_por_minuto` fora de "entre 1 e 6000"; informa **cada** campo inválido (FR-009); duas empresas criadas do modelo não compartilham listas nem dicionários (FR-008)
- [X] T006 [P] Escrever `tests/unit/test_ciclo_vida.py`: tabela de transições de [data-model.md](data-model.md) (`em_configuracao -> ativo`, `ativo <-> suspenso`, `em_configuracao|ativo|suspenso -> encerrado`); `encerrado` não volta; mensagem de erro cita estado atual e estados permitidos (`Transicao invalida: ativo -> em_configuracao. Permitido a partir de ativo: suspenso, encerrado.`)
- [X] T007 [P] Estender `tests/integration/test_migrations.py` para a 0004: `upgrade head`, `downgrade 0003`, `upgrade head`; `tenants.status` só aceita `em_configuracao`, `ativo`, `suspenso`, `encerrado` (CHECK); `trial -> em_configuracao` e `cancelado -> encerrado` no upgrade e o inverso no downgrade; `slug` preenchido e único; as 4 tabelas novas com `relrowsecurity` e `relforcerowsecurity`; CHECKs de `tenant_config`; `plantao_app` sem `UPDATE` nem `DELETE` em `audit_log`; escrita cruzada em `channel_connections` falha e leitura de roteamento funciona sem tenant
- [X] T008 [P] Escrever `tests/integration/test_auditoria.py`: `registrar_mudanca` grava uma linha por campo com valor anterior, valor novo, operador e data; a linha entra na **mesma transação** da mudança (rollback desfaz as duas); credencial vira `"<atualizada>"` e nunca aparece o valor; `plantao_app` não consegue `UPDATE` nem `DELETE` em `audit_log` (FR-029)
- [X] T009 [P] Escrever `tests/integration/test_conexoes.py`: cadastro grava `webhook_secret_hash` (`sha256`, 64 caracteres, nunca o segredo) e `api_key_enc` (Fernet, decifra de volta); mesmo `instance_name` em outra empresa é recusado com `ConexaoEmUso` (FR-002); segundo canal igual na mesma empresa recusado por `UNIQUE (tenant_id, canal)`; segredo com menos de 32 caracteres recusado; reexecutar com o mesmo valor não audita, com valor novo audita `credencial` sem o valor; empresa B não lê `channel_credentials` de A

### Implementação

- [X] T010 [P] Criar `db/config_padrao.py` com `CONFIG_PADRAO` e uma função `nova_config_padrao()` que devolve **cópias** (listas e dicionários novos): `tom_de_voz = ""`, `horario_funcionamento = {}`, `limite_desconto_percentual = 0.0`, `topicos_proibidos = []`, `confianca_minima_handoff = 0.7`, `palavras_gatilho = PALAVRAS_GATILHO_PADRAO`, `router_confidence_threshold = 0.6`, `min_similarity = 0.30`, `handoff_ttl_minutos = 60`, `limite_mensagens_por_minuto = 60` (research R-07)
- [X] T011 Atualizar `db/models.py` conforme [data-model.md](data-model.md) (depende de T010): `Tenant` (+`slug` string(63) UNIQUE NOT NULL com padrão `^[a-z0-9]+(-[a-z0-9]+)*$`, `status` padrão `em_configuracao` com CHECK `em_configuracao|ativo|suspenso|encerrado`, +`ativado_em`, +`encerrado_em`, +`dados_apagados_em`, todos timestamptz null); `TenantConfig` (+`handoff_ttl_minutos` int NOT NULL padrão 60, +`limite_mensagens_por_minuto` int NOT NULL padrão 60, defaults de todos os campos vindos de `nova_config_padrao`); `Conversation` (+`iniciada_por` string(20) NOT NULL padrão `contato` com CHECK `contato|empresa`, +`recebida_em_suspensao` bool NOT NULL padrão false); novos modelos `ChannelConnection` (`instance_name` string(100) `UNIQUE (instance_name)`, `UNIQUE (tenant_id, canal)`), `ChannelCredential` (`connection_id` PK/FK `ON DELETE CASCADE`, `webhook_secret_hash` string(64), `api_key_enc` text), `ReadinessCheck` (`tipo` `prontidao|conversa_teste`, 4 booleanos null, `aprovado`, `detalhes` json) e `AuditLog` (`tenant_id` **sem FK**, `entidade` `config|estado|conexao|dados`, `campo`, `valor_anterior` e `valor_novo` json null, `operador` string(100), índice `(tenant_id, criado_em DESC)`)
- [X] T012 Criar `db/migrations/versions/0004_multitenancy.py` (depende de T011; **não editar 0001 a 0003**): colunas novas; `slug` preenchido (minúsculas, sem acento, hífens; ex.: `clinica-sorriso-piloto`) e `UNIQUE`; remapeia `status` e aplica o CHECK; CHECKs de `tenant_config` (`confianca_minima_handoff`, `router_confidence_threshold`, `min_similarity` entre 0 e 1; `limite_desconto_percentual` entre 0 e 100; `handoff_ttl_minutos` entre 1 e 1440; `limite_mensagens_por_minuto` entre 1 e 6000); cria as 4 tabelas; `ENABLE` e `FORCE ROW LEVEL SECURITY` com política `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` (`USING` e `WITH CHECK`); em `channel_connections` política `FOR SELECT USING (true)` mais políticas de escrita por tenant; `GRANT SELECT, INSERT, UPDATE, DELETE` nas 3 tabelas e `GRANT SELECT, INSERT` em `audit_log`; `downgrade` reverte tudo e restaura `status` (research R-15)
- [X] T013 [P] Adicionar `purge_drenagem_segundos: int = 120` em `core/config.py` (variável `PURGE_DRENAGEM_SEGUNDOS`; research R-11). A remoção dos campos antigos fica em T037 e T053
- [X] T014 [P] Criar `core/tenancy/config.py` com `ConfigEmpresa` (pydantic v2, `extra="forbid"`) validando as faixas de T005 e devolvendo um erro por campo (depende de T010)
- [X] T015 [P] Criar `core/tenancy/ciclo_vida.py` com `Estado` (StrEnum), `TRANSICOES` e `validar_transicao` como funções puras
- [X] T016 Criar `core/tenancy/auditoria.py` com `registrar_mudanca(session, tenant_id, entidade, campo, anterior, novo, operador)`, que escreve na sessão recebida e substitui credenciais por `"<atualizada>"` (depende de T011)
- [X] T017 Criar `core/tenancy/conexoes.py` com `cadastrar_conexao` e `ConexaoEmUso` (Fernet com `get_cripto()`, `sha256` do segredo, validação de comprimento mínimo de 32, auditoria sem valores; depende de T016)
- [X] T018 Criar `core/tenancy/__init__.py` com `__all__` das APIs públicas de T014 a T017 (princípio II)
- [X] T019 Atualizar `tests/conftest.py` (depende de T012, T017): incluir `readiness_checks`, `audit_log`, `channel_credentials` e `channel_connections` no `TRUNCATE`; `criar_tenant` aceita `slug` (padrão derivado do nome e de um sufixo aleatório) e `status` (padrão `ativo`, para os testes existentes continuarem válidos); novo helper `criar_conexao(engine, tenant_id, instance_name=None, webhook_secret=None, api_key=None)` que devolve os valores em claro para o teste; fixture `tenant_c`; definir `PURGE_DRENAGEM_SEGUNDOS=0`; ajustar qualquer teste que construa `Tenant(` diretamente

**Checkpoint**: migração 0004 reversível, `ConfigEmpresa`, ciclo de vida, auditoria e conexões testados. `lint-imports` e `mypy` verdes nos módulos novos.

---

## Phase 3: User Story 1 - Cada mensagem é atendida pela empresa certa (Priority: P1) MVP

**Goal**: a mensagem identifica a empresa pela conexão de canal, autentica com o segredo daquela conexão, usa a
configuração e os documentos da empresa e responde pelo número dela. O tenant fixo deixa de existir.

**Independent Test**: com A e B ativas (documentos, desconto e tópicos diferentes), enviar a mesma pergunta pelo
webhook de cada uma e verificar no `FakeChannel` que cada resposta vem dos documentos da própria empresa, pela
conexão dela; token de A com instância de B é recusado; número desconhecido não grava nada; a empresa piloto
continua com os dados após a migração ([quickstart.md](quickstart.md) seções 2 e 5).

### Tests for User Story 1 (escrever primeiro; devem FALHAR)

- [X] T020 [P] [US1] Atualizar `tests/contract/test_whatsapp_channel.py` conforme [contracts/channel-port.md](contracts/channel-port.md): `send_text` e `verificar` com credencial por chamada; duas conexões enviam headers `apikey` diferentes; `verificar` com `open`, `close`, 404 e erro de rede; `repr(ConexaoCanal)` e `str(ChannelError)` sem `api_key`; `parse_inbound` extrai `instance` (string vazia se ausente) e continua ignorando `fromMe`, grupos e status
- [X] T021 [P] [US1] Reescrever `tests/contract/test_webhook.py` conforme [contracts/whatsapp-webhook.md](contracts/whatsapp-webhook.md): token de A com `instance` de B responde 401 e nada é gravado em B (SC-009); instância desconhecida, sem `instance` e token errado dão o mesmo status e o mesmo corpo; empresa `em_configuracao` e `encerrado` respondem `ignored` sem gravar mensagem nem conversa; mesmo `external_id` em duas empresas gera `queued` nas duas; limite excedido em A responde `rate_limited` e B continua `queued`; `_job_id` com formato `{tenant_id}:{message_id}`; logs do webhook sem telefone, conteúdo, token nem chave de envio
- [X] T022 [P] [US1] Escrever `tests/integration/test_resolucao.py`: `resolver_conexao` devolve `tenant_id` pelo `instance_name` sem contexto de tenant; `autenticar_entrega` aceita o segredo da conexão e recusa o de outra; instância desconhecida percorre o mesmo caminho de custo (hash falso); `carregar_conexao_canal` descriptografa `api_key_enc`; empresa sem credencial devolve erro tipado
- [X] T023 [P] [US1] Escrever `tests/integration/test_continuidade_piloto.py` (FR-032, SC-007): migrar até `0003`, inserir uma empresa legada (`status = trial`/`ativo`, conversas, documentos, trechos, configuração), aplicar `0004` e conferir que contagens e valores ficaram idênticos, `slug` preenchido e `status` mapeado; o `create` com o arquivo da piloto é validado em T052 e no [quickstart.md](quickstart.md) seção 2
- [X] T024 [P] [US1] Atualizar `tests/integration/test_pipeline.py`: o canal usa a conexão da empresa dona da conversa (`FakeChannel` registra `instance_name`); duas empresas, mesma pergunta, cada resposta dos próprios documentos; desconto 5% é enviado para A (limite 10%) e vira handoff `desconto_acima_do_limite` para B (limite 0%) (US1 cenário 2); TTL de handoff vem de `tenant_config.handoff_ttl_minutos` e não de `settings`; `ChannelError` grava `status_envio = falha` e handoff `falha_canal`; empresa sem conexão também gera `falha_canal`; `message_id` de outra empresa devolve `mensagem_inexistente`
- [X] T025 [P] [US1] Ajustar `tests/integration/test_registro_uso.py` e `tests/unit/test_orquestrador.py` à nova assinatura de `FakeChannel` e aos dois campos novos de `ConfigTenant`

### Implementation for User Story 1

- [X] T026 [P] [US1] Atualizar `core/ports/channel.py` conforme [contracts/channel-port.md](contracts/channel-port.md): `ConexaoCanal` (dataclass congelada, `api_key` com `field(repr=False)`), `EstadoConexao`, `send_text(conexao, contato, texto)` e `verificar(conexao)`
- [X] T027 [US1] Atualizar `tests/fakes/channel.py`: `FakeChannel` registra `(instance_name, contato, texto)`, aceita falha por `instance_name` e devolve estado configurável em `verificar` (depende de T026)
- [X] T028 [US1] Atualizar `integrations/whatsapp/client.py` (depende de T026): `MensagemEntrada.instance`; um `httpx.AsyncClient` compartilhado; credencial por chamada; `send_text` e `verificar` sem ler `settings.whatsapp_instance` nem `settings.whatsapp_api_key`; `ChannelError` com código curto sem credencial
- [X] T029 [P] [US1] Adicionar `MOTIVO_FALHA_CANAL = "falha_canal"` em `core/handoff/textos.py` (sem texto ao cliente, porque o canal falhou)
- [X] T030 [P] [US1] Acrescentar `handoff_ttl_minutos` e `limite_mensagens_por_minuto` a `ConfigTenant` e a `ConfigTenant.de_modelo` em `agents/orchestrator/state.py`
- [X] T031 [US1] Criar `core/tenancy/resolucao.py` (depende de T017, T026): `resolver_conexao(instance)` lê o diretório em sessão sem tenant; `autenticar_entrega(conexao, token)` abre `tenant_session(conexao.tenant_id)` **apenas para ler o hash**, compara em tempo constante e, para instância desconhecida, calcula um hash falso; `carregar_conexao_canal(session, tenant_id, canal)` monta `ConexaoCanal` descriptografando `api_key_enc` (research R-01, R-02)
- [X] T032 [P] [US1] Atualizar `db/repositories.py`: `carregar_estado_empresa(session)` e as travas `travar_estado_compartilhada(session, tenant_id)` e `travar_estado_exclusiva(session, tenant_id)` com `pg_advisory_xact_lock_shared` e `pg_advisory_xact_lock` sobre `hashtextextended('estado_empresa:' || tenant_id, 0)` (research R-06); `obter_ou_criar_conversa` mantém `iniciada_por = contato`
- [X] T033 [P] [US1] Remover `get_tenant_id()` de `apps/api/deps.py` (docstring e função); nenhuma dependência de tenant fixo permanece
- [X] T034 [US1] Reescrever `apps/api/webhooks/whatsapp.py` na ordem de [contracts/whatsapp-webhook.md](contracts/whatsapp-webhook.md) (depende de T028, T031, T032, T033): corpo, resolução, autenticação, `definir_contexto(tenant_id, correlation_id)`, estado da empresa (apenas `ativo` segue; `em_configuracao` e `encerrado` respondem `ignored` sem gravar; `suspenso` fica para T067), limite `limite_mensagens_por_minuto` da configuração, persistência e `enqueue_job(..., _job_id=f"{tenant_id}:{message_id}")`; logs `conexao_desconhecida`, `token_invalido`, `empresa_nao_ativa` e `rate_limited` sem dados pessoais; manter o `GET` de verificação da Meta
- [X] T035 [US1] Atualizar `apps/worker/jobs.py` (depende de T029, T030, T031, T032): TTL do handoff vem de `config.handoff_ttl_minutos`; a conexão é carregada por `carregar_conexao_canal` e passada a `channel.send_text`; `ChannelError` ou conexão ausente grava `status_envio = falha`, chama `registrar_handoff(motivo=MOTIVO_FALHA_CANAL)` e registra `canal_falhou` com o código do erro; o tenant do job só vale se a mensagem existir dentro dele (RLS)
- [X] T036 [P] [US1] Ajustar `apps/composition.py` e `apps/worker/settings.py`: um único canal compartilhado entre empresas, sem leitura de instância ou chave global; `on_startup` continua chamando `exigir_segredos()`
- [X] T037 [US1] Limpar `core/config.py` (depende de T034, T035, T036): remover `whatsapp_instance`, `whatsapp_api_key`, `whatsapp_webhook_secret`, `rate_limit_msgs_per_min` e `handoff_ttl_minutes`; `exigir_segredos()` passa a exigir só `PII_ENCRYPTION_KEY` e `PII_HASH_KEY`; remover `WHATSAPP_WEBHOOK_SECRET` do ambiente em `tests/conftest.py` e corrigir qualquer teste que ainda leia os campos removidos (`settings.handoff_ttl_minutes` em `tests/integration/test_pipeline.py`)

**Checkpoint**: US1 funcional e testável sozinha, com `lint-imports`, `mypy` e `pytest -q tests/contract tests/integration/test_resolucao.py tests/integration/test_pipeline.py` verdes.

---

## Phase 4: User Story 2 - Operador cria uma nova empresa por procedimento repetível (Priority: P1)

**Goal**: `python -m scripts.tenants create --file empresa.yml` cria a empresa, aplica a configuração, conecta o número,
indexa documentos e permite verificar a prontidão e ativar, sem alterar código e sem duplicar nada ao repetir.

**Independent Test**: de um arquivo e uma pasta de documentos, criar uma empresa nova, rodar `readiness`, executar o
`test`, `activate` e receber uma resposta correta; repetir o `create` no meio e no fim sem duplicar; ativação com
pendência é recusada ([quickstart.md](quickstart.md) seções 3 e 4).

### Tests for User Story 2 (escrever primeiro; devem FALHAR)

- [X] T038 [P] [US2] Escrever `tests/unit/test_arquivo_empresa.py`: `ArquivoEmpresa` com `extra="forbid"` recusa campo desconhecido; `slug` fora de `^[a-z0-9]+(-[a-z0-9]+)*$` ou fora de 3 a 63 caracteres; confiança fora de 0 a 1 e desconto acima de 100 (um erro por campo, US2 cenário 6); `horario_funcionamento` fora de `HH:MM-HH:MM`; `canal.tipo` e `canal.provedor` só aceitam `whatsapp` e `evolution`; variável de ambiente ausente ou vazia e segredo de entrega com menos de 32 caracteres citam só o **nome** da variável
- [X] T039 [P] [US2] Escrever `tests/unit/test_prontidao_regras.py`: `config_completa` exige `tom_de_voz` não vazio e `horario_funcionamento` não vazio; `conversa_teste_valida` só aceita teste aprovado mais novo que a última linha de auditoria `entidade = config` e que o maior `knowledge_documents.atualizado_em`; `avaliar_resposta_teste` aprova ação `responder` que contém todos os termos esperados (comparação normalizada) ou qualquer `responder` quando não há termos; reprova handoff e exceção
- [X] T040 [P] [US2] Escrever `tests/integration/test_onboarding.py`: criação do zero fica `em_configuracao` com configuração, conexão e documentos (FR-012); segundo `create` não duplica empresa, conexão nem documentos (`inalterado`) e não gera linha de auditoria; interrupção no passo de documentos (LLM fake falha) seguida de repetição conclui o restante (FR-013); empresa `ativo` repetida continua `ativo`; `instance_name` de outra empresa é recusado e nada novo fica gravado; arquivo inválido não cria nada; mudança de um campo gera uma linha de auditoria por campo alterado; nenhum valor de credencial em stdout, stderr nem logs
- [X] T041 [P] [US2] Escrever `tests/integration/test_prontidao.py`: cada item pendente isolado (configuração incompleta, zero documentos, conexão não verificada, sem teste aprovado) faz a ativação ser recusada e listar o item (SC-010); alterar a configuração ou atualizar um documento depois do teste invalida o item 4; prontidão aprovada ativa, grava `ativado_em` e uma linha de auditoria `estado` com operador, estado anterior e novo (FR-015); `verificar` do `FakeChannel` grava `verificada_em`
- [X] T042 [P] [US2] Escrever `tests/integration/test_tenants_cli.py`: saídas de `create`, `readiness`, `activate`, `list` e `status` no formato de [contracts/tenants-cli.md](contracts/tenants-cli.md); códigos de saída 0, 1 e 2; `--operador` obrigatório em comando que altera algo
- [X] T043 [P] [US2] Atualizar `tests/integration/test_ingest_cli.py` e `tests/unit/test_evals.py` para `--tenant SLUG` obrigatório (sem ele, código 2 e nada gravado) e remover o `monkeypatch` de `pilot_tenant_id`

### Implementation for User Story 2

- [X] T044 [P] [US2] Criar `db/admin.py` com a fábrica de sessão do papel administrativo (`DATABASE_ADMIN_URL`, `NullPool` em teste), usada só por `scripts/` e por `core/tenancy` quando recebe a sessão por parâmetro (research R-16)
- [X] T045 [P] [US2] Criar `core/tenancy/empresas.py` com `obter_por_slug(session, slug)`, `listar(session)` e `EmpresaNaoEncontrada` (depende de T011)
- [X] T046 [US2] Estender `core/tenancy/ciclo_vida.py` com `mudar_estado(session, tenant_id, novo, operador)`: pega `travar_estado_exclusiva`, valida a transição, atualiza `tenants.status` e o carimbo correspondente (`ativado_em` na primeira ativação, `encerrado_em`) e chama `registrar_mudanca(entidade="estado")` na mesma transação (depende de T015, T016, T032)
- [X] T047 [US2] Criar `core/tenancy/prontidao.py` (depende de T014, T026, T046): `avaliar_prontidao` com os 4 itens e `verificar` pela porta `MessageChannel`; grava `readiness_checks` (`tipo = prontidao`); `registrar_teste` grava `tipo = conversa_teste`; `ativar` reavalia os itens 1 a 3, valida o 4, recusa listando pendências e chama `mudar_estado` (research R-10)
- [X] T048 [US2] Criar `core/tenancy/onboarding.py` (depende de T014, T017, T045): `ArquivoEmpresa` conforme [contracts/onboarding-file.md](contracts/onboarding-file.md) e `criar_ou_continuar` com os passos de research R-09 (empresa por `slug`, configuração mesclada com `CONFIG_PADRAO` e auditada só nos campos alterados, conexão, credenciais lidas do ambiente, documentos por `ingerir_documento`, tempo por passo); valida tudo **antes** de escrever; não rebaixa empresa `ativo`
- [X] T049 [US2] Criar `scripts/tenants.py` com `argparse` e os comandos `create`, `list`, `status`, `readiness`, `test` e `activate` (depende de T044 a T048): saídas e códigos de [contracts/tenants-cli.md](contracts/tenants-cli.md); `test` executa o `Grafo` com `ConfigTenant.de_modelo` do banco, sem gravar em `messages`, e registra o resultado; credenciais nunca impressas (FR-005)
- [X] T050 [US2] Atualizar `scripts/ingest_docs.py` (depende de T044, T045): `--tenant SLUG` obrigatório em `load`, `list` e `remove`; resolve o `slug` com o papel administrativo e opera por `tenant_session`; sem empresa padrão (FR-021)
- [X] T051 [US2] Atualizar `scripts/run_evals.py` (depende de T044, T045): `--tenant SLUG` obrigatório; remover o uso de `settings.tenant_piloto()`
- [X] T052 [P] [US2] Criar `docs/exemplos/empresa-modelo.yml` (esquema completo comentado) e `docs/exemplos/piloto.yml` com `slug: clinica-sorriso-piloto`, a configuração atual da piloto (hoje em `scripts/seed_tenant.py`) e `teste_prontidao`; sem segredos
- [X] T053 [US2] Remover `scripts/seed_tenant.py`, `pilot_tenant_id` e `tenant_piloto()` de `core/config.py`, `PILOT_TENANT_ID` do `tests/conftest.py` e o alvo `seed` do `Makefile` (depende de T050, T051)

**Checkpoint**: criar, verificar e ativar uma empresa funciona de ponta a ponta com LLM e canal fakes.

---

## Phase 5: User Story 3 - Isolamento entre empresas é comprovado por testes (Priority: P1)

**Goal**: a suíte de isolamento com 3 empresas cobre todas as entidades e o fluxo completo, roda em toda alteração
do código e **falha** quando o isolamento é quebrado de propósito.

**Independent Test**: criar A, B e C com dados distintos e executar `pytest -q tests/integration -k isolamento`; tudo
passa; remover uma política de RLS faz a suíte falhar ([quickstart.md](quickstart.md) seção 6).

### Tests for User Story 3 (escrever primeiro; os casos novos devem FALHAR até T062)

- [X] T054 [P] [US3] Criar documentos fictícios com marcadores únicos em `tests/evals/docs_empresa_b/` e `tests/evals/docs_empresa_c/` (horário, preço e tópico proibido diferentes de `docs_piloto`) e `tests/evals/isolamento.yaml` com 30 perguntas por empresa e o marcador que **não** pode aparecer na resposta de cada uma
- [X] T055 [P] [US3] Reescrever `tests/integration/test_isolamento_tenants.py` com A, B e C: para cada tabela com `tenant_id` (`tenant_config`, `tenant_knowledge`, `knowledge_documents`, `conversations`, `messages`, `leads`, `appointments`, `billing_events`, `usage_metrics`, `handoff_log`, `llm_calls`, `channel_connections` (escrita), `channel_credentials`, `readiness_checks`, `audit_log`) verifica leitura, escrita cruzada, ausência de contexto devolvendo 0 linhas e busca vetorial; mantém um registro `ENTIDADES_COBERTAS` (FR-028, SC-003)
- [X] T056 [P] [US3] Escrever `tests/integration/test_isolamento_cobertura.py`: consulta `information_schema` e `pg_class`; falha se existir tabela com coluna `tenant_id` sem `relrowsecurity` e `relforcerowsecurity`, sem política, ou fora de `ENTIDADES_COBERTAS` (research R-14, item 2)
- [X] T057 [P] [US3] Escrever `tests/integration/test_isolamento_quebra.py`: numa transação revertida, remove a política de uma tabela e roda a matriz de T055; o teste **espera** que a matriz falhe, provando que a suíte detecta o vazamento (research R-14, item 3; SC-003)
- [X] T058 [P] [US3] Escrever `tests/integration/test_isolamento_pipeline.py` (webhook e worker com canal e LLM fakes): mesmo telefone em A e B gera duas conversas sem histórico compartilhado (FR-024); mesmo `external_id` é processado e respondido uma vez por empresa (FR-025); limite excedido em A não afeta B e ≥ 90% das mensagens de B respondem em até 10 s (FR-026, SC-006); falha de canal em A não afeta B e vira handoff só em A (FR-027); chaves Redis `rl:{tenant}:*` separadas; job com `tenant_id` trocado devolve `mensagem_inexistente` (US3 cenários 2 a 5)
- [X] T059 [P] [US3] Acrescentar caso adversarial em `tests/adversarial/test_adversarial.py` e `tests/evals/adversariais.yaml`: mensagem do cliente da empresa A pede "os preços da outra clínica" e contém texto de um documento de B; a resposta não pode conter o marcador de B (constituição, princípios III e V; escrito antes de qualquer correção)

### Implementation for User Story 3

- [X] T060 [US3] Adicionar a suíte `isolamento` ao `scripts/run_evals.py` com `--tenants a,b,c` (depende de T051, T054): cada pergunta vai para a empresa dona, e o resultado procura marcadores de outras empresas; mede SC-002 (100% com base própria, 0% com marcador alheio)
- [X] T061 [P] [US3] Estender `tests/unit/test_evals.py` com a medida SC-002 da suíte `isolamento` (marcador alheio faz a meta falhar; sem marcador passa)
- [X] T062 [US3] Rodar `pytest -q tests/integration -k isolamento tests/adversarial` e corrigir cada vazamento encontrado no código de produção (`apps/`, `core/`, `db/`), sem relaxar a suíte; registrar no PR o que foi corrigido (depende de T055 a T059)

**Checkpoint**: US1 a US3 completas. MVP liberável para o segundo cliente depois da validação do [quickstart.md](quickstart.md) seções 2 a 6.

---

## Phase 6: User Story 4 - Operador suspende e reativa uma empresa (Priority: P2)

**Goal**: pausar uma empresa em até 1 minuto, inclusive para mensagens já na fila, sem afetar as demais, guardando
as mensagens recebidas; reativar preserva o histórico.

**Independent Test**: com A e B ativas e mensagens na fila, suspender A; A não responde mais, B segue normal; as
mensagens recebidas por A ficam guardadas e marcadas; ao reativar, A volta a responder ([quickstart.md](quickstart.md)
seção 7, passos 1 a 4).

### Tests for User Story 4 (escrever primeiro; devem FALHAR)

- [X] T063 [P] [US4] Escrever `tests/integration/test_ciclo_vida.py`: `suspend` e `resume` válidos e inválidos com mensagem de transição; mensagem enfileirada antes da suspensão devolve `empresa_inativa` e não envia (início do job); a checagem na gravação impede resposta quando o estado muda durante o grafo (a mudança de estado espera a trava advisory de quem já gravava); mensagem recebida suspensa fica guardada com `recebida_em_suspensao = true` e sem job; reativação não reprocessa o backlog; B mantém a meta de 10 s em ≥ 90% durante a suspensão de A (SC-004); linha de auditoria `estado` com anterior, novo, operador e data
- [X] T064 [US4] Estender `tests/contract/test_webhook.py` com a linha `suspenso` da tabela de efeitos: `200 {"status":"suspended"}`, mensagem gravada com marca, nenhum job (depende de T021)

### Implementation for User Story 4

- [X] T065 [P] [US4] Atualizar `db/repositories.py`: `obter_ou_criar_conversa(..., recebida_em_suspensao=False)` marca `recebida_em_suspensao = true` na conversa nova ou reutilizada quando recebe mensagem com a empresa suspensa (FR-017)
- [X] T066 [US4] Acrescentar `suspender` e `retomar` a `core/tenancy/ciclo_vida.py` sobre `mudar_estado` (depende de T046)
- [X] T067 [US4] Tratar o estado `suspenso` em `apps/api/webhooks/whatsapp.py`: grava a mensagem com a marca, não enfileira e responde `suspended` (depende de T034, T065)
- [X] T068 [US4] Aplicar o estado no worker em `apps/worker/jobs.py` (depende de T032, T035): no início, estado diferente de `ativo` devolve `empresa_inativa`; na transação de `_gravar`, `travar_estado_compartilhada` e nova leitura do estado antes de gravar a resposta; se não estiver `ativo`, não grava nem envia (research R-06)
- [X] T069 [US4] Adicionar `suspend` (`--motivo` opcional, vai para a auditoria) e `resume` a `scripts/tenants.py` (depende de T049, T066)
- [X] T070 [P] [US4] Criar `docs/RUNBOOK_INCIDENTE.md` (seção 8.10 do projeto): como pausar e retomar uma empresa, o que acontece com a fila e com as mensagens recebidas, como conferir `audit`, ordem de deploy da migração 0004 com o `create` da piloto (research R-15) e o requisito `BYPASSRLS` do papel administrativo em produção (research R-16)

**Checkpoint**: pausa rápida de uma empresa documentada e testada.

---

## Phase 7: User Story 5 - Operador ajusta a configuração sem afetar as outras (Priority: P2)

**Goal**: alterar regras de uma empresa com validação e auditoria por campo, valendo na próxima mensagem, sem
reiniciar e sem tocar nas outras.

**Independent Test**: mudar `limite_desconto_percentual` de A; a próxima mensagem de A usa o novo valor, B mantém o
dela, existe registro com anterior, novo, operador e data; valor inválido é recusado ([quickstart.md](quickstart.md) seção 8).

### Tests for User Story 5 (escrever primeiro; devem FALHAR)

- [X] T071 [P] [US5] Escrever `tests/unit/test_config_alteracoes.py`: `campo=valor` interpreta JSON (`0.8`, `["a","b"]`, `{"seg_sex":"08:00-18:00"}`) e trata texto sem aspas como string; campo desconhecido é erro; vários campos são validados juntos
- [X] T072 [P] [US5] Escrever `tests/integration/test_config_auditoria.py`: alteração válida vale na próxima mensagem do pipeline sem reinício (FR-010); mensagem já respondida não é reprocessada; B continua com a configuração dela; uma linha de auditoria por campo com anterior, novo, operador e data; valor inválido recusa **toda** a alteração e preserva o valor anterior (US5 cenário 3); `CONFIG_PADRAO` não muda ao editar uma empresa (FR-008)

### Implementation for User Story 5

- [X] T073 [US5] Adicionar `aplicar_alteracoes(session, tenant_id, alteracoes, operador)` a `core/tenancy/config.py`: valida o conjunto com `ConfigEmpresa`, grava só o que mudou e chama `registrar_mudanca(entidade="config")` na mesma transação (depende de T014, T016)
- [X] T074 [US5] Adicionar `config show`, `config set` e `audit` a `scripts/tenants.py` (depende de T049, T073): saídas de [contracts/tenants-cli.md](contracts/tenants-cli.md); `--operador` obrigatório em `config set`; falha lista cada campo inválido

**Checkpoint**: configuração por empresa auditável e válida na próxima mensagem.

---

## Phase 8: User Story 6 - Operador encerra uma empresa e apaga os dados dela (Priority: P3)

**Goal**: encerrar bloqueia respostas; `purge` com confirmação pelo nome apaga todos os dados da empresa sem tocar
nas outras e libera o número.

**Independent Test**: criar C com conversas, documentos e uso; encerrar e apagar; nada de C resta, A e B estão
idênticas, o número é liberado e a auditoria da exclusão existe sem dado pessoal ([quickstart.md](quickstart.md) seção 7, passo 5).

### Tests for User Story 6 (escrever primeiro; devem FALHAR)

- [X] T075 [P] [US6] Escrever `tests/integration/test_exclusao_dados.py`: `close` deixa de responder e mantém o número reservado (FR-020); `purge` sem `--confirmar` correto não apaga nada; `purge` antes da drenagem (`PURGE_DRENAGEM_SEGUNDOS` > 0 nesse teste) recusa; `purge` correto zera todas as entidades de C e as chaves `rl:{tenant}:*` no Redis; contagens de A e B idênticas antes e depois (SC-008); número liberado para outra empresa só depois; `tenants` guarda a marca (`dados_apagados_em`, nome, `slug`); `audit_log` tem a linha `dados` com operador e data e **nenhum** dado de cliente final; job em andamento durante o `close` não envia resposta

### Implementation for User Story 6

- [X] T076 [US6] Criar `core/tenancy/exclusao.py` (depende de T046, T075): `encerrar` (via `mudar_estado`); `apagar_dados` valida estado `encerrado`, confirmação exata do nome e drenagem cumprida; apaga em uma transação `tenant_session` (papel `plantao_app`, RLS protegendo as outras empresas) na ordem `handoff_log`, `llm_calls`, `appointments`, `leads`, `messages`, `conversations`, `billing_events`, `usage_metrics`, `tenant_knowledge`, `knowledge_documents`, `readiness_checks`, `channel_credentials`, `channel_connections`, `tenant_config` e registra `audit_log` (`entidade = dados`, só nome e `slug`); depois, com o papel administrativo, grava `dados_apagados_em` (idempotente se repetir) e remove as chaves `rl:{tenant}:*` do Redis (research R-11)
- [X] T077 [US6] Adicionar `close` e `purge --confirmar "NOME"` a `scripts/tenants.py` (depende de T049, T076): saída com contagens apenas numéricas, código 1 em recusa
- [X] T078 [US6] Fazer `scripts/ingest_docs.py` recusar (código 1) empresa `encerrado` (depende de T050)

**Checkpoint**: ciclo de vida completo (criar, ativar, suspender, reativar, encerrar, apagar).

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: gates de qualidade, documentação e validações que dependem de serviços reais.

- [X] T079 [P] Escrever `tests/unit/test_admin_isolado.py`: nenhum arquivo em `apps/` referencia `database_admin_url` nem `db.admin` (research R-16)
- [X] T080 [P] Atualizar o `Makefile` com `tenant-create`, `tenant-readiness`, `tenant-activate`, `tenant-suspend`, `tenant-resume` (`FILE=`, `TENANT=`, `OPERADOR=`) e exigir `TENANT=` em `make ingest` e `make evals`
- [X] T081 [P] Atualizar `README.md`: setup sem `PILOT_TENANT_ID`, fluxo de onboarding, comandos do operador, variáveis de ambiente por empresa e ordem de deploy da 0004
- [X] T082 Rodar a pipeline de qualidade (`pytest --cov`, `ruff`, `mypy`, `lint_imports`) e fechar lacunas: 80% em `core` e `agents`, 100% em `core/guardrails`; `alembic downgrade 0003` e `upgrade head`
- [X] T083 Executar `pip-audit` e `gitleaks` no repositório inteiro e corrigir achados (princípio IV)
- [X] T084 [P] Criar `docs/SPRINT_3_RESULTADOS.md` com as medidas de SC-001 a SC-010 (automáticas e manuais)
- [ ] T085 Executar a validação completa de [quickstart.md](quickstart.md) (seções 1 a 9). **Pendente: exige OpenRouter e Evolution API reais**
- [ ] T086 Medir SC-001 em 2 criações consecutivas de empresa (tabela do quickstart, seção 3, passo 8). **Pendente: exige trabalho manual e Evolution real**
- [ ] T087 Rodar `python -m scripts.run_evals --suite isolamento --tenants a,b,c` com LLM real (SC-002). **Pendente: exige `OPENROUTER_API_KEY`**
- [X] T088 Registrar na constituição (rodapé de decisões) a exceção de leitura aberta em `channel_connections` e o uso do papel administrativo em `scripts/`, e referenciar os ADRs 0003 e 0004 (Governance)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sem dependências. T004 precisa terminar antes de T028 e T034 se a contingência for necessária.
- **Foundational (Phase 2)**: depende de Setup; bloqueia todas as stories. Dentro da fase: T010 antes de T011 e T014; T011 antes de T012, T016 e T017; T012 e T017 antes de T019.
- **US1 (Phase 3)**: depende de Foundational. Remove o tenant fixo do webhook e do worker.
- **US2 (Phase 4)**: depende de US1 (porta de canal, resolução, `ConfigTenant`) e de T046 antes de T047.
- **US3 (Phase 5)**: depende de US1 e US2 (precisa criar empresas e conexões pelos helpers e rodar `run_evals --tenant`).
- **US4 (Phase 6)**: depende de US1 e de T046 (US2).
- **US5 (Phase 7)**: depende de T014, T016 e T049.
- **US6 (Phase 8)**: depende de T046, T049 e T050.
- **Polish (Phase 9)**: depende das stories desejadas.

### Dentro de cada story

- Testes primeiro e falhando; depois portas e modelos; depois serviços; depois endpoints e CLI.
- US1, US2 e US4 editam `apps/worker/jobs.py`, `apps/api/webhooks/whatsapp.py` e `scripts/tenants.py`; US2 a US6 editam `core/tenancy/ciclo_vida.py` e `scripts/tenants.py`: executar em ordem, sem paralelismo entre stories.

### Dependências críticas entre tarefas

- T012 depende de T011; T019 depende de T012 e T017.
- T028 depende de T026; T031 depende de T017 e T026; T034 depende de T028, T031, T032 e T033; T035 depende de T029 a T032; T037 só depois de T034 a T036.
- T046 depende de T015, T016 e T032; T047 de T014, T026 e T046; T049 de T044 a T048; T053 de T050 e T051.
- T062 só depois de T055 a T059. T067 depende de T034 e T065; T068 de T032 e T035.
- T076 depende de T046; T077 de T049 e T076.

## Parallel Opportunities

- Phase 1: T002, T003 e T004 em paralelo após T001.
- Phase 2: T005 a T009 (testes) em paralelo; T010, T013 e T015 em paralelo; T014 e T016 em paralelo após T010 e T011.
- US1: T020 a T025 em paralelo; depois T026, T029, T030, T032, T033 e T036 em paralelo.
- US2: T038 a T043 em paralelo; T044, T045 e T052 em paralelo.
- US3: T054 a T059 em paralelo; T060 e T061 em paralelo.
- Polish: T079, T080, T081 e T084 em paralelo.

### Exemplo: User Story 1

```text
Tarefas em paralelo (testes):
  T020 tests/contract/test_whatsapp_channel.py
  T021 tests/contract/test_webhook.py
  T022 tests/integration/test_resolucao.py
  T023 tests/integration/test_continuidade_piloto.py
  T024 tests/integration/test_pipeline.py

Tarefas em paralelo (implementação base):
  T026 core/ports/channel.py
  T029 core/handoff/textos.py
  T030 agents/orchestrator/state.py
  T032 db/repositories.py
  T033 apps/api/deps.py
```

## Implementation Strategy

### MVP first (US1 + US2 + US3)

1. Phase 1 e Phase 2 completas.
2. US1, depois US2, depois US3, validando cada checkpoint com os testes da story.
3. PARAR e validar com [quickstart.md](quickstart.md) seções 1 a 6 antes de colocar o segundo cliente em produção.
4. Rodar o `create` da empresa piloto (`docs/exemplos/piloto.yml`) no mesmo deploy da migração 0004 (research R-15).

### Entrega incremental

1. Foundational pronta: schema, modelo padrão, auditoria e conexões testados.
2. US1: o webhook e o worker deixam de depender de empresa fixa.
3. US2: segunda empresa criada por comando repetível.
4. US3: prova de isolamento no CI (MVP liberável).
5. US4 e US5: pausa rápida e ajuste de regras (necessários antes de cobrar).
6. US6: encerramento e exclusão de dados.
7. Polish: gates, documentação e medições manuais.

## Notes

- [P] significa arquivos diferentes e sem dependência pendente.
- Confirmar que cada teste falha antes de implementar.
- Fazer commit a cada tarefa ou grupo lógico (Conventional Commits, PRs pequenos).
- Nenhum segredo (chave de envio, segredo de entrega) em saída de comando, log, mensagem de erro ou auditoria (FR-005).
- Nenhum telefone em texto puro em banco, fila ou logs (princípio IV).
- Agendamento, SDR, cobrança, painel, fila de atendentes, outros canais e chaves por empresa ficam fora do escopo (spec).
