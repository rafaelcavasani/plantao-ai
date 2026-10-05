# Data Model: Multi-tenancy real

Baseado em `db/models.py` e em [specs/001-router-support-agent/data-model.md](../001-router-support-agent/data-model.md).
Todas as mudanças chegam pela migração Alembic **0004_multitenancy** (reversível; a 0003 não é editada).

Convenções: `PK` chave primária, `FK` chave estrangeira. Toda tabela nova tem `tenant_id NOT NULL` com índice e
RLS habilitado e forçado para `plantao_app`, na mesma forma da 0003 (`tenant_id = NULLIF(current_setting(
'app.tenant_id', true), '')::uuid`, `USING` e `WITH CHECK`). Exceções declaradas abaixo.

## Entidades alteradas

### tenants (ALTERADA)

| Coluna | Tipo | Observação |
|---|---|---|
| id, nome_empresa, nicho, plano, criado_em | existentes | |
| **slug** | string(63) UNIQUE NOT NULL | chave natural do onboarding (R-09). Backfill: nome em minúsculas, sem acento, hífens (`clinica-sorriso-piloto`). Padrão `^[a-z0-9]+(-[a-z0-9]+)*$` |
| status | string(50) | passa a `em_configuracao` \| `ativo` \| `suspenso` \| `encerrado` (CHECK). Mapeamento: `trial -> em_configuracao`, `cancelado -> encerrado` |
| **ativado_em** | timestamptz null | data da primeira ativação (a autoria fica em `audit_log`) |
| **encerrado_em** | timestamptz null | início do encerramento; base da drenagem (R-11) |
| **dados_apagados_em** | timestamptz null | preenchido pela exclusão; a linha vira marca (nome e `slug` preservados) |

RLS inalterada (`id = app.tenant_id`). `plantao_app` continua só com `SELECT`.

Transições (validadas em `core/tenancy/ciclo_vida.py`, testadas sem banco):

| De | Para | Condição |
|---|---|---|
| (nova) | em_configuracao | `create` |
| em_configuracao | ativo | prontidão aprovada (4 itens) |
| ativo | suspenso | nenhuma |
| suspenso | ativo | nenhuma |
| em_configuracao, ativo, suspenso | encerrado | nenhuma |
| encerrado | (apagar dados) | confirmação pelo nome e drenagem cumprida |

Qualquer outra transição é recusada com mensagem que cita estado atual e estados permitidos. `encerrado` não volta.

### tenant_config (ALTERADA)

| Coluna | Tipo | Observação |
|---|---|---|
| tenant_id | uuid PK, FK | existente |
| tom_de_voz, horario_funcionamento, limite_desconto_percentual, topicos_proibidos, confianca_minima_handoff, palavras_gatilho, router_confidence_threshold, min_similarity | existentes | valores padrão vêm de `CONFIG_PADRAO` |
| **handoff_ttl_minutos** | int NOT NULL, padrão 60 | substitui `settings.handoff_ttl_minutes` (FR-007) |
| **limite_mensagens_por_minuto** | int NOT NULL, padrão 60 | substitui `settings.rate_limit_msgs_per_min` (FR-007, FR-026) |

CHECKs (defesa em profundidade, além do pydantic):

| Campo | Regra |
|---|---|
| confianca_minima_handoff, router_confidence_threshold, min_similarity | entre 0 e 1 |
| limite_desconto_percentual | entre 0 e 100 |
| handoff_ttl_minutos | entre 1 e 1440 |
| limite_mensagens_por_minuto | entre 1 e 6000 |

`CONFIG_PADRAO` (`db/config_padrao.py`):

```text
tom_de_voz = ""                          horario_funcionamento = {}
limite_desconto_percentual = 0.0         topicos_proibidos = []
confianca_minima_handoff = 0.7           palavras_gatilho = PALAVRAS_GATILHO_PADRAO
router_confidence_threshold = 0.6        min_similarity = 0.30
handoff_ttl_minutos = 60                 limite_mensagens_por_minuto = 60
```

Cada empresa recebe **cópias** (listas e dicionários novos), então editar uma nunca altera o modelo (FR-008).

### conversations (ALTERADA)

| Coluna | Tipo | Observação |
|---|---|---|
| id, tenant_id, canal, contato_hash, contato_enc, status, agente_atual, ultima_atividade_em, handoff_em, iniciado_em | existentes | `iniciado_em` responde "quando" de FR-030 |
| **iniciada_por** | string(20) NOT NULL, padrão `contato` | `contato` \| `empresa` (CHECK). Só `contato` é criado nesta entrega |
| **recebida_em_suspensao** | bool NOT NULL, padrão false | verdadeiro quando a mensagem chegou com a empresa suspensa (FR-017) |

Índice de busca existente `(tenant_id, canal, contato_hash, ultima_atividade_em DESC)` já contém `tenant_id`, o
que garante conversas separadas para o mesmo telefone em empresas diferentes (FR-024).

### messages (sem mudança de colunas)

`UNIQUE (tenant_id, external_id) WHERE external_id IS NOT NULL` já cobre FR-025 (mesmo `external_id` em duas
empresas). `UNIQUE (responde_a)` continua. Os testes de isolamento ganham um cenário explícito para ambos.

### handoff_log (sem mudança de colunas)

Novo código de motivo: `falha_canal` (conexão da empresa recusou ou falhou ao enviar).

## Entidades novas

### channel_connections (diretório de roteamento)

| Coluna | Tipo | Observação |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid FK `tenants.id` | |
| canal | string(50) | `whatsapp` |
| provedor | string(30) | `evolution` hoje |
| instance_name | string(100) | identificador do número no provedor; **UNIQUE global** (FR-002) |
| verificada_em | timestamptz null | última verificação bem-sucedida (item 3 da prontidão) |
| criado_em | timestamptz | |

Restrições: `UNIQUE (instance_name)`; `UNIQUE (tenant_id, canal)` (R-04).

RLS (exceção declarada, R-01): habilitado e forçado, com `FOR SELECT USING (true)` e políticas de
`INSERT/UPDATE/DELETE` por `tenant_id = app.tenant_id` (`USING` e `WITH CHECK`). Sem colunas sensíveis.

### channel_credentials

| Coluna | Tipo | Observação |
|---|---|---|
| connection_id | uuid PK, FK `channel_connections.id` ON DELETE CASCADE | |
| tenant_id | uuid FK | |
| webhook_secret_hash | string(64) | `sha256` do segredo de entrega (R-02, R-03) |
| api_key_enc | text | Fernet da chave de envio (R-03) |
| atualizado_em | timestamptz | |

RLS padrão por `tenant_id`. Nunca selecionada junto com o diretório aberto, nunca registrada em log ou auditoria.

### readiness_checks

| Coluna | Tipo | Observação |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid FK | |
| executado_em | timestamptz | |
| operador | string(100) | nome informado no comando |
| tipo | string(20) | `prontidao` (4 itens avaliados) \| `conversa_teste` (execução da simulação) |
| config_ok, documentos_ok, conexao_ok, conversa_teste_ok | bool null | itens da verificação; null quando o registro é de outro tipo |
| aprovado | bool | `prontidao`: todos verdadeiros; `conversa_teste`: critério de R-10 |
| detalhes | json | pendências por item, sem segredos e sem texto de cliente final |

Regra de validade do item 4: existe `conversa_teste` com `aprovado = true` e `executado_em` maior que a última
alteração de configuração (`audit_log`, `entidade = config`) e que o maior `knowledge_documents.atualizado_em`.

### audit_log (append-only, sem FK)

| Coluna | Tipo | Observação |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid NOT NULL | **sem FK** (R-08, Complexity Tracking) para sobreviver à exclusão |
| entidade | string(20) | `config` \| `estado` \| `conexao` \| `dados` |
| campo | string(100) | nome do campo; `status`, `instance_name`, `credencial`, `exclusao` etc. |
| valor_anterior | json null | |
| valor_novo | json null | `"<atualizada>"` no lugar de qualquer credencial (FR-029) |
| operador | string(100) | |
| criado_em | timestamptz | |

Índice `(tenant_id, criado_em DESC)`. RLS por `tenant_id`; `plantao_app` com `SELECT` e `INSERT` apenas (sem
`UPDATE` nem `DELETE`). Linhas de exclusão guardam `{"nome_empresa": ..., "slug": ...}`, nunca dado de cliente final.

## Entidades que continuam iguais

`knowledge_documents`, `tenant_knowledge`, `messages`, `leads`, `appointments`, `billing_events`, `usage_metrics`,
`handoff_log`, `llm_calls` mantêm colunas e RLS. Todas entram na matriz de isolamento (R-14) e na ordem de
exclusão (R-11).

## Tabelas com RLS (lista usada pela migração e pela introspecção)

`tenant_config`, `tenant_knowledge`, `knowledge_documents`, `conversations`, `messages`, `leads`, `appointments`,
`billing_events`, `usage_metrics`, `handoff_log`, `llm_calls` (0003) e as novas `channel_connections`,
`channel_credentials`, `readiness_checks`, `audit_log` (0004). `tenants` mantém a política própria.

## Migração 0004 (resumo)

`upgrade`:

1. `tenants`: colunas novas; `slug` preenchido e `UNIQUE`; remapeia `status`; CHECK de `status`.
2. `tenant_config`: duas colunas com defaults e CHECKs.
3. `conversations`: `iniciada_por` e `recebida_em_suspensao`.
4. Cria `channel_connections`, `channel_credentials`, `readiness_checks`, `audit_log`; RLS, políticas e `GRANT`
   (`audit_log` só `SELECT, INSERT`).

`downgrade`: remove as quatro tabelas e as colunas novas, restaura `status` (`em_configuracao -> trial`,
`encerrado -> cancelado`) e remove o CHECK. Dados de empresa existentes (piloto) não são alterados no `upgrade`
além do mapeamento de `status` e do `slug`.

## Validação (resumo por requisito)

| Requisito | Onde é garantido |
|---|---|
| FR-002 | `UNIQUE (instance_name)` e `UNIQUE (tenant_id, canal)` |
| FR-005 | `api_key_enc` Fernet, `webhook_secret_hash`; nenhuma coluna de segredo em tabela aberta |
| FR-009 | pydantic `ConfigEmpresa` + CHECKs em `tenant_config` |
| FR-011 | CHECK em `tenants.status` + `ciclo_vida` |
| FR-022 | RLS em todas as tabelas de negócio; sem contexto devolve 0 linhas |
| FR-025 | índice único `(tenant_id, external_id)` |
| FR-029 | `audit_log` na mesma transação da mudança |
| FR-030 | `conversations.iniciada_por` + `iniciado_em` |
