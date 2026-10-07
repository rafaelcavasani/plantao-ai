# Data Model: Painel de operação de empresas

Migração nova: `db/migrations/versions/0005_painel.py` (revisão `0005`, depende de `0004`). Reversível. As migrações
anteriores não são editadas. Todas as definições abaixo são de **desenho**; os tipos exatos saem na implementação.

## 1. Alterações em tabelas existentes

| Tabela | Mudança | Motivo |
|---|---|---|
| `tenants` | `versao int not null default 1` | Concorrência otimista (research R-05, FR-040). Incrementada por todo serviço de escrita do painel. |

Nenhuma outra coluna muda. `tenants.plano` passa a guardar a chave do plano (`recepcionista`, `recepcionista_agendador`,
`pacote_completo`); valores antigos continuam válidos e `recepcionista` segue como padrão.

## 2. Tabelas novas

### 2.1 `painel_agregado_hora`

Uma linha por empresa e hora (UTC). Chave primária `(tenant_id, hora)`. Índice em `(hora)`.

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `tenant_id` | uuid, FK `tenants.id` | Obrigatório (princípio III) |
| `hora` | timestamptz | Início da hora, UTC |
| `msgs_lead`, `msgs_agente`, `msgs_humano` | int | `messages.remetente` na hora |
| `msgs_nao_texto` | int | `messages.tipo = 'nao_texto'` |
| `conversas_iniciadas` | int | `conversations.iniciado_em` na hora |
| `handoffs` | int | linhas de `handoff_log` na hora |
| `handoffs_resolvidos` | int | linhas de `handoff_log` com `resolvido_por_humano` |
| `bloqueios_guardrail` | int | `handoff_log` cujo `motivo` não está em `nao_texto`, `falha_canal`, `mensagem_vazia`, `desconhecido`, `entrada_reprovada`, `saida_reprovada` (research R-15) |
| `falhas_envio` | int | `messages` do agente com `status_envio = 'falha'` |
| `resp_n`, `resp_soma_ms` | int, bigint | par mensagem do contato → resposta do agente (`responde_a`) |
| `resp_hist` | jsonb (int[11]) | histograma em baldes fixos (R-12) |
| `intencoes` | jsonb | contagem por `messages.intencao` |
| `tokens_entrada`, `tokens_saida` | bigint | soma de `llm_calls` |
| `custo_usd` | numeric(14,6) | soma de `llm_calls.custo_usd` |
| `custo_roteador`, `custo_suporte`, `custo_embedding` | numeric(14,6) | por `llm_calls.finalidade` |
| `custo_por_modelo` | jsonb | `{modelo: custo_usd}` |
| `atualizado_em` | timestamptz | quando o job gravou a linha |

Regras:
- Escrita só pelo job, sob `tenant_session`, por **upsert** idempotente (recalcular a mesma hora dá o mesmo resultado).
- Nenhuma coluna guarda texto, contato ou identificador de conversa.
- Retenção de 400 dias (R-18).

### 2.2 `painel_situacao`

Uma linha por empresa (estado corrente). Chave primária `tenant_id`.

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `tenant_id` | uuid, FK | PK |
| `ultima_mensagem_em` | timestamptz null | maior `messages.timestamp` |
| `ultimo_remetente` | text null | `lead`, `agente` ou `humano` dessa mensagem |
| `conversas_abertas` | int | `conversations.status = 'aberta'` |
| `conversas_handoff` | int | `conversations.status = 'handoff'` (aguardando pessoa) |
| `documentos`, `trechos` | int | `knowledge_documents` (contagem e soma de `num_trechos`) |
| `atualizado_em` | timestamptz | quando o job gravou |

Quando a empresa é encerrada com dados apagados (`dados_apagados_em`), o job para de atualizar e a linha é removida pelo
`purge` (R-18); a ficha mostra "dados apagados em <data>".

## 3. Privilégios e RLS

### 3.1 Papel `plantao_painel`

`CREATE ROLE plantao_painel LOGIN PASSWORD <PAINEL_DB_PASSWORD> NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`,
criado na migração (mesmo padrão da 0003). Só `SELECT`; nenhum `INSERT`, `UPDATE`, `DELETE`.

| Tabela | Colunas liberadas ao `plantao_painel` |
|---|---|
| `tenants` | todas |
| `tenant_config` | todas |
| `channel_connections` | todas (sem segredos) |
| `readiness_checks` | todas |
| `audit_log` | todas (valores de credencial já são marcas) |
| `handoff_log` | todas |
| `knowledge_documents` | `id, tenant_id, nome_origem, versao, num_trechos, atualizado_em` |
| `conversations` | `id, tenant_id, canal, status, agente_atual, ultima_atividade_em, handoff_em, iniciado_em, iniciada_por, recebida_em_suspensao` |
| `messages` | `id, tenant_id, conversation_id, remetente, tipo, intencao, intencao_confianca, status_envio, timestamp` |
| `llm_calls` | nenhuma (o custo vem de `painel_agregado_hora`) |
| `painel_agregado_hora`, `painel_situacao` | todas |
| `channel_credentials`, `knowledge`/`tenant_knowledge`, `leads`, `appointments`, `billing_events` | **nenhuma** |

**Fora do alcance por construção**: `messages.conteudo`, `messages.external_id`, `conversations.contato_hash`,
`conversations.contato_enc`, `channel_credentials.*`, `tenant_knowledge.chunk_texto`.

### 3.2 Políticas RLS

As tabelas já têm `ENABLE` e `FORCE ROW LEVEL SECURITY`. Para cada tabela da coluna acima, a migração acrescenta:

```text
CREATE POLICY painel_leitura ON <tabela> FOR SELECT TO plantao_painel USING (true);
```

As políticas existentes por `app.tenant_id` não mudam, então o `plantao_app` continua isolado por empresa. Nas duas tabelas
novas, o `plantao_app` ganha `SELECT, INSERT, UPDATE, DELETE` com a política padrão por `tenant_id` (é ele quem as escreve,
sob `tenant_session`). `audit_log` continua só `SELECT, INSERT` para o `plantao_app`.

### 3.3 Testes exigidos pelo modelo

- `has_column_privilege('plantao_painel', 'messages', 'conteudo', 'SELECT')` é falso; idem para `contato_enc`,
  `contato_hash`, `external_id` e para qualquer coluna de `channel_credentials`.
- Introspecção: toda tabela nova tem `tenant_id NOT NULL`, RLS forçado e política de isolamento (extensão do teste de
  isolamento da spec 002).
- Duas empresas: a soma da visão geral é a soma das duas; a ficha de uma não traz linha da outra.

## 4. Estado fora do banco

### 4.1 Configuração em arquivo

`db/config_planos.py`:

```text
PLANOS = {
  "recepcionista":            {"nome": "Recepcionista",             "orcamento_mensal_usd": <valor|None>, "preco_mensal_usd": <valor|None>},
  "recepcionista_agendador":  {"nome": "Recepcionista + Agendador", ...},
  "pacote_completo":          {"nome": "Pacote completo",           ...},
}
```

Valores iniciais definidos pelo negócio no PR da implementação (o plano não os inventa). Plano ausente ou sem valor: o painel
mostra "sem orçamento" e "margem indisponível".

### 4.2 Variáveis de ambiente novas (`.env.example` atualizado na implementação)

| Variável | Uso | Padrão |
|---|---|---|
| `DATABASE_PAINEL_URL` | conexão do papel `plantao_painel` | `postgresql+asyncpg://plantao_painel:plantao_painel@localhost:5432/plantao` |
| `PAINEL_DB_PASSWORD` | senha do papel na migração | `plantao_painel` (só desenvolvimento) |
| `OPERADORES` | `email:papel,email:papel` (`leitura` ou `operacao`) | vazio (ninguém entra) |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` | provedor de identidade | vazios |
| `PAINEL_AUTH_MODE` | `oidc` ou `dev` (`dev` só com `ENV=development`) | `oidc` |
| `PAINEL_SESSAO_INATIVIDADE_MIN` / `PAINEL_SESSAO_MAXIMA_H` | expiração (FR-006) | `30` / `12` |
| `PAINEL_LIMITE_SILENCIO_HORAS` | alerta "sem atividade" (FR-012) | `24` |
| `PAINEL_LIMITE_HANDOFF_PCT` | alerta de handoff | `30` |
| `PAINEL_LIMITE_CUSTO_PCT` | alerta de custo | `90` |
| `PAINEL_ESCRITA_POR_MINUTO` | limite de taxa por operador | `60` |

### 4.3 Redis (chaves com prefixo `painel:`)

| Chave | Conteúdo | Expiração |
|---|---|---|
| `painel:sessao:{sha256(token)}` | `{email, papel, criada_em, ultima_atividade}` | deslizante, 30 min; teto 12 h |
| `painel:oidc:{state}` | `{nonce, code_verifier, destino}` | 10 min |
| `painel:rl:{email}:{minuto}` | contador de escrita | 90 s |
| `painel:atualizar:lock` | marca de atualização em curso | 20 s |
| `painel:remessa:{id}` | arquivos da remessa e resultado por arquivo | 1 h |

Nenhuma chave guarda dado pessoal de cliente final. O `purge` de uma empresa já limpa chaves por `tenant_id`; as chaves
`painel:*` não são por empresa, exceto `remessa`, que carrega o `slug` e expira sozinha.

## 5. Entidades da spec e onde vivem

| Entidade da spec | Onde vive |
|---|---|
| Operador | e-mail em `OPERADORES` + sessão no Redis; o e-mail vai para `audit_log.operador` |
| Empresa (tenant) | `tenants` (+ `versao`), `tenant_config`, `channel_connections` |
| Resumo de atividade | `painel_agregado_hora` (período) e `painel_situacao` (agora) |
| Alerta de atenção | calculado em `core/painel/atencao.py`; **não persistido** |
| Limites de atenção | variáveis `PAINEL_LIMITE_*` |
| Tabela de planos | `db/config_planos.py` |
| Conexão, documento, prontidão, auditoria | tabelas existentes |

## 6. Transições de estado

Sem mudança: `core/tenancy/ciclo_vida.py` (`em_configuracao → ativo | encerrado`, `ativo → suspenso | encerrado`,
`suspenso → ativo | encerrado`, `encerrado → ∅`). O painel só chama `mudar_estado` e mostra os destinos permitidos que a API
devolve em cada ficha (`acoes_permitidas`), para a tela nunca divergir da regra.
