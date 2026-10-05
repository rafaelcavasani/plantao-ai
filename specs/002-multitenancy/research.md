# Research: Multi-tenancy real

Todas as decisões abaixo resolvem pontos em aberto do Technical Context de [plan.md](plan.md). Nenhum item
`NEEDS CLARIFICATION` permanece. Valores numéricos são **iniciais** e ajustáveis por empresa (spec, Assumptions).
Itens marcados **Confirmar** dependem de verificação contra a Evolution API real durante a implementação e têm
plano de contingência.

## R-01. Como descobrir a empresa antes de existir `tenant_id` na sessão

- **Decision**: duas tabelas.
  - `channel_connections` (diretório de roteamento): `id`, `tenant_id`, `canal`, `provedor`, `instance_name`
    (UNIQUE global), `verificada_em`, `criado_em`. RLS habilitado e forçado com duas políticas: `FOR SELECT USING
    (true)` (leitura de roteamento) e `FOR INSERT/UPDATE/DELETE` restritas a `tenant_id = app.tenant_id`.
  - `channel_credentials` (segredos): `connection_id` PK/FK, `tenant_id`, `webhook_secret_hash`, `api_key_enc`,
    `atualizado_em`. RLS por `tenant_id`, como as demais tabelas.
  O webhook lê o diretório numa sessão sem tenant, obtém `tenant_id` e abre `tenant_session` para o resto.
- **Rationale**: só colunas sem segredo ficam legíveis entre empresas. Um vazamento por SQL injection ou bug na
  API expõe o mapa "instância -> empresa", não credenciais. A restrição de escrita impede que a API troque a
  conexão de outra empresa.
- **Alternatives considered**: (a) função `SECURITY DEFINER`: o dono da tabela está sujeito a `FORCE ROW LEVEL
  SECURITY` e só a ignora se for superusuário ou `BYPASSRLS`, o que é verdade no Docker e incerto em produção;
  (b) consultar com o papel administrativo no webhook: dá à API inteira um papel que ignora RLS;
  (c) um tenant por subdomínio ou por caminho da URL (`/webhooks/whatsapp/{tenant}`): expõe o id da empresa e
  não resolve a autenticação, só desloca o problema.
- **Risco**: a política de leitura aberta é a única exceção do princípio III; entra em Complexity Tracking e é
  coberta por teste (segredo nunca está na tabela aberta; escrita cruzada falha).

## R-02. Autenticação da entrega por conexão (FR-003, SC-009)

- **Decision**: o payload da Evolution traz `instance` no nível raiz (nome da instância = a conexão). O webhook
  usa esse valor só como **chave de busca**; a autenticação é o header `X-Webhook-Token` comparado em tempo
  constante com o `webhook_secret_hash` **daquela conexão** (`sha256(token)` contra o hash salvo). Instância
  desconhecida, token ausente e token errado respondem o mesmo `401 {"detail":"invalid token"}`, com tempo
  parecido (calcula-se um hash falso quando a instância não existe).
- **Rationale**: uma entrega assinada com o segredo de A que declare `instance = B` falha porque o hash de B não
  confere. Resposta uniforme impede descobrir quais instâncias existem. O segredo é aleatório e longo (>= 32
  bytes), então `sha256` simples basta; não há senha de humano para proteger com KDF lento.
- **Alternatives considered**: segredo global (hoje) com `instance` confiável: qualquer entrega válida grava em
  qualquer empresa, o oposto de FR-003; HMAC do corpo com chave por conexão: a Evolution não assina o corpo,
  só envia header customizado; id da conexão na URL: segue possível mais tarde como alternativa para o canal
  oficial da Meta, sem mudar o restante.
- **Confirmar**: a Evolution aceita `headers` por instância no `webhook/set/{instance}` e inclui `instance` no
  corpo de `messages.upsert`. Contingência: usar o id opaco da conexão na URL (`/webhooks/whatsapp/{connection_id}`)
  e conferir `instance` do corpo contra a conexão; a mudança fica em `apps/api/webhooks` e `parse_inbound`.

## R-03. Credenciais por empresa e saída sem segredos (FR-005)

- **Decision**: o arquivo de onboarding guarda **nomes de variáveis de ambiente** (`api_key_env`,
  `webhook_secret_env`), não valores. O comando lê o valor do ambiente, grava `api_key_enc` com Fernet (a chave
  única de PII da plataforma, conforme a spec) e `webhook_secret_hash`. Saída, log e auditoria registram só
  "credencial atualizada" e a data. Rotação é rodar o comando de novo com a variável nova.
- **Rationale**: respeita FR-005 (nenhum comando imprime credencial) e evita segredo em arquivo versionável. O
  operador gera o segredo de entrega (`secrets.token_urlsafe(32)`) e o configura nos dois lados: variável de
  ambiente do comando e header do webhook da Evolution.
- **Alternatives considered**: o comando gerar e imprimir o segredo uma vez (viola FR-005); guardar o segredo de
  entrega criptografado em vez de hash (permite recuperar, o que ninguém precisa); secret manager externo
  (infraestrutura sem necessidade no MVP).
- **Consequência de segurança**: `ConexaoCanal.api_key` usa `field(repr=False)`; `FormatadorJson` já mascara só
  telefone, então o teste de saída percorre logs e stdout de todos os comandos procurando os valores de teste.

## R-04. Uma conexão por empresa e canal

- **Decision**: `UNIQUE (tenant_id, canal)` em `channel_connections`. A conversa **não** ganha `connection_id`;
  o worker resolve a conexão pela empresa e pelo canal da conversa.
- **Rationale**: a spec define um número por empresa e deixa número compartilhado e vários números fora de
  escopo. Evita coluna e backfill sem uso (princípio VIII).
- **Alternatives considered**: `conversations.connection_id` desde já: custo de migração e de teste para um caso
  que não existe. Se várias conexões por empresa surgirem, a mudança é uma coluna nova mais um índice.

## R-05. Ciclo de vida e onde ele é aplicado (FR-011, FR-015 a FR-018)

- **Decision**: `tenants.status` passa a aceitar `em_configuracao`, `ativo`, `suspenso`, `encerrado` (CHECK).
  Mapeamento da migração: `trial -> em_configuracao`, `ativo -> ativo`, `suspenso -> suspenso`,
  `cancelado -> encerrado`. Transições válidas ficam em uma tabela em `core/tenancy/ciclo_vida.py`, usada pelo
  CLI e testada sem banco. O estado é **lido do banco** no webhook, no começo do job e dentro da transação que
  grava a resposta; nunca fica em cache.
- **Rationale**: ler a cada mensagem custa uma consulta por chave primária e torna suspensão e reativação
  imediatas (a spec aceita até 1 minuto), sem invalidação de cache nem tarefa de sincronização.
- **Alternatives considered**: cache em memória com TTL de 30 s (estado global, que o princípio II proíbe, e
  atraso na suspensão); flag no Redis (segunda fonte de verdade para o mesmo dado).

## R-06. Suspensão e mensagens em andamento (FR-016, FR-017, SC-004)

- **Decision**:
  1. **Webhook**: empresa suspensa grava a mensagem do lead numa conversa marcada
     `recebida_em_suspensao = true`, **não enfileira** e responde `200 {"status":"suspended"}`. Em configuração
     ou encerrada: `200 {"status":"ignored"}`, sem gravar nada.
  2. **Worker, início**: lê `tenants.status`; se não for `ativo`, devolve `empresa_inativa` sem chamar o grafo.
  3. **Worker, gravação**: na transação que grava a resposta, `pg_advisory_xact_lock_shared(<chave da
     empresa>)` e depois `SELECT status FROM tenants`; se não for `ativo`, não grava nem envia. A mudança de
     estado (CLI) pega `pg_advisory_xact_lock(<mesma chave>)` antes do `UPDATE tenants`, então espera quem já
     passou pela trava e não existe resposta gravada depois do estado novo. Lock de linha (`FOR SHARE`) não
     serve: exige privilégio `UPDATE` em `tenants`, que o papel `plantao_app` não tem e não deve ter. Chave:
     `hashtextextended('estado_empresa:' || tenant_id, 0)`.
  4. **Reativação**: só mensagens novas são respondidas. Mensagens guardadas durante a suspensão ficam no
     histórico e **não** são reprocessadas (evita rajada de respostas atrasadas e fora de contexto).
- **Rationale**: fecha a janela "mensagem já na fila" exigida em FR-016 com duas checagens baratas e uma trava
  de linha. Não reprocessar é a escolha segura para incidente (spec, Assumptions).
- **Alternatives considered**: remover jobs da fila ao suspender (ARQ não tem consulta por empresa; o id do job
  tem prefixo, mas varrer a fila é frágil); reprocessar o backlog na reativação (decisão de negócio que a spec não
  pediu; fica como evolução).
- **Janela residual**: entre o fim da gravação e o `send_text` (milissegundos a poucos segundos) uma resposta
  já autorizada pode sair. É aceitável para FR-016 (limite de 1 minuto) e é tratada por R-11 na exclusão.

## R-07. Configuração por empresa e modelo padrão (FR-007 a FR-010)

- **Decision**:
  - Valores padrão em `db/config_padrao.py` (`CONFIG_PADRAO`), fonte única usada pelos defaults de
    `TenantConfig`, pelo modelo pydantic e pelo onboarding. Fica em `db/` porque `db` não pode importar `core`.
  - Duas colunas novas em `tenant_config`: `handoff_ttl_minutos` (padrão 60) e `limite_mensagens_por_minuto`
    (padrão 60), substituindo `settings.handoff_ttl_minutes` e `settings.rate_limit_msgs_per_min`.
  - Validação em `core/tenancy/config.py` (`ConfigEmpresa`, pydantic v2) **e** CHECK no Postgres
    (`confianca_minima_handoff`, `router_confidence_threshold`, `min_similarity` entre 0 e 1;
    `limite_desconto_percentual` entre 0 e 100; `handoff_ttl_minutos` entre 1 e 1440;
    `limite_mensagens_por_minuto` entre 1 e 6000).
  - Config lida do banco a cada mensagem (como hoje no worker; o webhook passa a ler o limite).
  - "Configuração completa" (prontidão) exige `tom_de_voz` não vazio e `horario_funcionamento` não vazio, que
    nascem vazios no modelo padrão.
- **Rationale**: duas camadas de validação cobrem tanto a CLI quanto qualquer gravação futura. Fonte única
  atende FR-008 (editar uma empresa nunca altera o modelo, pois cada empresa recebe uma cópia).
- **Valores iniciais** (assumption da spec sobre limites): 60 mensagens/min, repasse humano 60 min, confiança
  mínima 0,7, roteador 0,6, similaridade 0,30, desconto 0%, gatilhos padrão atuais. Mesmos números da 001; só
  mudam de lugar.
- **Alternatives considered**: JSON único `config` (perde validação por coluna e índices); cache com
  invalidação por Redis pub/sub (complexidade sem ganho, ver R-05).

## R-08. Auditoria (FR-029, FR-030)

- **Decision**: tabela `audit_log` append-only: `tenant_id` (sem FK), `entidade` (`config`, `estado`,
  `conexao`, `dados`), `campo`, `valor_anterior` e `valor_novo` (JSON), `operador`, `criado_em`. Uma linha por
  campo alterado. Para `conexao`, o valor de credencial é substituído por `"<atualizada>"`. O papel da aplicação
  tem só `SELECT` e `INSERT`; não há `UPDATE` nem `DELETE`. A escrita acontece **na mesma transação** da
  mudança.
- **Rationale**: transação única garante que não existe mudança sem registro nem registro sem mudança. Sem FK
  porque a linha da exclusão precisa sobreviver (US6 cenário 4). Uma linha por campo atende "campo, valor
  anterior, valor novo" da US5 e facilita consulta.
- **Origem do contato (FR-030)**: coluna `conversations.iniciada_por` (`contato` | `empresa`, padrão
  `contato`); quando começou já é `iniciado_em`. Na etapa atual só existe `contato`.
- **Alternatives considered**: triggers no Postgres (registram o autor errado, pois o operador não é um usuário
  do banco); event sourcing (excesso para o MVP).

## R-09. Onboarding repetível por arquivo (FR-012, FR-013)

- **Decision**: `scripts/tenants.py create --file empresa.yml --operador NOME`, `argparse` como em
  `ingest_docs.py`. O arquivo (YAML, esquema em [contracts/onboarding-file.md](contracts/onboarding-file.md))
  tem chave natural `slug`. Passos, cada um um upsert dentro da sua transação:
  1. validar o arquivo inteiro (nada é criado se houver erro, US2 cenário 6);
  2. empresa (`slug` único) em `em_configuracao`; se já existe, reutiliza e **não rebaixa** uma empresa ativa;
  3. configuração: `CONFIG_PADRAO` mesclado com o arquivo, validado; só grava e audita os campos que mudaram;
  4. conexão: `instance_name` livre ou da própria empresa; se pertence a outra, recusa (FR-002);
  5. credenciais (R-03);
  6. documentos: `ingerir_documento` já é idempotente por hash (`inalterado`);
  7. resumo sem segredos e tempo gasto por passo (insumo de SC-001).
  Interrupção em qualquer passo deixa a empresa em `em_configuracao`; repetir o comando continua de onde parou.
- **Dependência**: `pyyaml` vira dependência de runtime (hoje só dev). Já é usada por `scripts/run_evals.py`;
  YAML aceita comentários e é legível para quem não programa, o que importa para o operador.
- **Rationale**: upsert por passo é mais simples e testável que um log de progresso; o estado real é o próprio
  banco.
- **Alternatives considered**: JSON (sem comentários); TOML (já usado em `pyproject`, mas listas de tabelas
  aninhadas ficam piores para horário e gatilhos); comando interativo (não é repetível nem versionável);
  `typer`/`click` (nova dependência sem ganho).

## R-10. Prontidão e conversa simulada (FR-014, FR-015, SC-010)

- **Decision**: quatro itens, avaliados a cada pedido e na ativação:
  1. configuração completa e válida (R-07);
  2. ao menos 1 documento em `knowledge_documents` com `num_trechos > 0`;
  3. conexão cadastrada **e verificada**: `MessageChannel.verificar(conexao)` consulta o estado da instância e
     grava `verificada_em`;
  4. conversa simulada aprovada: `tenants.py test <slug>` executa o grafo do orquestrador, sem gravar em
     `messages`, com a pergunta e os termos esperados do arquivo (`teste_prontidao`), e registra o resultado em
     `readiness_checks`. Vale só se for **mais nova** que a última mudança de configuração (`audit_log`) e que a
     última atualização de documento.
  A ativação **reavalia** os itens 1 a 3 e valida o 4; recusa e lista o que falta (SC-010).
- **Rationale**: reaproveita o mesmo caminho de `run_evals.py` (offline, sem tocar nas conversas), cumpre "conversa
  de teste" sem enviar mensagem real e impede ativar com configuração alterada depois do teste. O grafo roda em
  `scripts/` para não violar `core` não importa `agents`.
- **Aprovação do teste**: resposta com ação `responder` contendo todos os termos esperados, ou, se o arquivo
  não os definir, ação `responder` qualquer. Handoff ou exceção reprova.
- **Confirmar**: estado da instância na Evolution (`GET /instance/connectionState/{instance}` com `apikey` da
  instância, estado `open`). Contingência: item 3 passa a depender de um `ping` de envio para o próprio número de
  teste do operador, definido no arquivo.
- **Alternatives considered**: simular via webhook real (grava dados e envia mensagem de verdade); marcar a
  prontidão como flag manual (não prova nada).

## R-11. Encerramento e exclusão de dados (FR-019, FR-020, SC-008)

- **Decision**:
  - `close` muda o estado para `encerrado`, grava `encerrado_em`; o número continua reservado.
  - `purge` exige estado `encerrado`, a confirmação `--confirmar "<nome exato da empresa>"` e que o encerramento
    tenha pelo menos `DRENAGEM_SEGUNDOS` (padrão 120 s, igual a `job_timeout` do worker). Em testes o valor é 0.
  - Numa única transação com `app.tenant_id` da empresa, apaga na ordem das FKs: `handoff_log`, `llm_calls`,
    `appointments`, `leads`, `messages`, `conversations`, `billing_events`, `usage_metrics`,
    `tenant_knowledge`, `knowledge_documents`, `readiness_checks`, `channel_credentials`,
    `channel_connections`, `tenant_config`. Mantém a linha de `tenants` como **marca**
    (`dados_apagados_em`, nome, `slug`) e `audit_log`.
  - Fora do banco: remove as chaves `rl:{tenant}:*` do Redis.
  - Libera o número porque `channel_connections` foi apagada (FR-020).
  - Registra em `audit_log` (`entidade = dados`, quem, quando, empresa), sem nenhum dado de cliente final.
- **Rationale**: a drenagem fecha a janela residual de R-06 (jobs em andamento terminam em até `job_timeout`);
  a trava advisory (R-06) + estado `encerrado` impede novos envios. A marca em `tenants` evita reuso do `slug` e
  mantém a prova de existência. RLS garante que o `DELETE` só alcança linhas da empresa; o teste compara
  contagens de A e B antes e depois (SC-008).
- **Alternatives considered**: apagar a linha de `tenants` (perde o vínculo da auditoria com o nome);
  `TRUNCATE` por empresa (inexistente); particionamento por empresa (excesso para 10 empresas).
- **ADR**: 0004 registra a decisão e a retenção da marca.

## R-12. Fila, limite e justiça entre empresas (FR-023, FR-026, SC-006)

- **Decision**: continua **uma fila ARQ e um worker**. Cada job leva `tenant_id`; o `_job_id` passa a ser
  `"{tenant_id}:{message_id}"`; o job abre `tenant_session` e, por RLS, não enxerga mensagem de outra empresa
  (id trocado devolve `mensagem_inexistente`). O limite por minuto vem de `tenant_config`
  (`limite_mensagens_por_minuto`) e usa a chave Redis já prefixada `rl:{tenant}:{minuto}`; excedente recebe
  `rate_limited` e **não entra na fila**.
- **Rationale**: como o excesso é descartado no webhook, o volume que uma empresa coloca na fila é limitado a
  `limite × 1 min`, o que protege a latência das outras (SC-006). Fila separada por empresa exigiria workers
  configurados dinamicamente.
- **Alternatives considered**: uma fila por empresa (ARQ liga o worker a nomes de fila fixos); prioridade
  ponderada (sem carga real para calibrar). Reavaliar se uma empresa legítima chegar perto do limite padrão.
- **Medição**: o teste de SC-006 enfileira acima do limite de A e mede a latência de B com o canal fake.

## R-13. Falha de canal isolada (FR-004, FR-027)

- **Decision**: `MessageChannel.send_text(conexao, contato, texto)`. O cliente HTTP é um pool único compartilhado
  e **a credencial vai por chamada**, então uma falha não contamina outras empresas. Em `ChannelError`, o job
  marca `status_envio = falha`, chama `registrar_handoff(motivo="falha_canal")` e registra
  `canal_falhou` no log (código do erro, sem credencial). Nenhuma outra empresa é tocada.
- **Rationale**: é o menor desvio da porta atual e permite trocar a Evolution pela Meta mudando só
  `integrations/`.
- **Alternatives considered**: um cliente por empresa guardado em memória (estado global e ciclo de vida do pool
  por empresa); circuit breaker por conexão (sem volume que o justifique).

## R-14. Prova de isolamento (FR-028, SC-003)

- **Decision**: a suíte de isolamento passa a ter quatro partes, todas em `tests/integration/`:
  1. **Matriz por entidade com 3 empresas**: popula A, B e C, e para cada tabela com `tenant_id` verifica leitura,
     escrita cruzada, ausência de contexto, busca vetorial, contadores, fila e credenciais.
  2. **Introspecção**: consulta `information_schema` e `pg_class`; falha se existir tabela com `tenant_id` sem
     `relrowsecurity` e `relforcerowsecurity`, sem política, ou sem cenário no registro de cobertura da suíte.
  3. **Quebra proposital**: numa transação revertida, remove a política de uma tabela e roda a mesma matriz; o
     teste espera que ela **falhe**, provando que a suíte detecta o vazamento.
  4. **Ponta a ponta**: duas empresas no webhook e no worker com canal e LLM fakes: mesma pergunta, mesmo
     `external_id`, mesmo telefone, credencial trocada, falha no canal de A, limite excedido em A.
- **Rationale**: itens 2 e 3 transformam o requisito "cada entidade com dado de empresa tem cenário" em uma regra
  que quebra o CI quando alguém esquece, em vez de depender de revisão.
- **Medição manual (SC-002)**: `run_evals --suite isolamento --tenants a,b,c` com LLM real, 30 perguntas por
  empresa, procurando marcadores únicos das outras empresas nas respostas (CI não usa LLM real).

## R-15. Migração 0004 e continuidade da empresa piloto (FR-032, SC-007)

- **Decision**: `0004_multitenancy` é apenas de schema e de mapeamento de dados que não dependem de segredo:
  novas tabelas e colunas, `slug` preenchido a partir do nome (`clinica-sorriso-piloto`), mapeamento de
  `status`, CHECKs, RLS e `GRANT`s (`audit_log` com `SELECT`/`INSERT`). `downgrade` remove tudo que o `upgrade`
  criou e restaura os valores de `status`. A conexão da piloto **não** é criada pela migração (dependeria de
  segredos e da chave de PII): o operador roda uma vez
  `python -m scripts.tenants create --file docs/exemplos/piloto.yml`, que encontra a empresa pelo `slug`,
  mantém `ativo` e adiciona a conexão e os documentos (que ficam `inalterado`).
- **Rationale**: migrações não devem ler segredos nem chamar serviços externos; o passo único fica explícito
  no runbook e é idempotente. Conversas, documentos e configuração da piloto não são tocados.
- **Janela de transição**: entre a migração e o `create` da piloto, o webhook responde 401 (instância sem
  conexão). O runbook manda rodar os dois no mesmo deploy, com a Evolution parada ou aceitando reentrega.
- **Remoções**: `settings.pilot_tenant_id`, `tenant_piloto()`, `whatsapp_instance`, `whatsapp_api_key`,
  `whatsapp_webhook_secret` (valores por conexão), `rate_limit_msgs_per_min`, `handoff_ttl_minutes` (agora na
  configuração). `exigir_segredos()` passa a exigir só `PII_ENCRYPTION_KEY` e `PII_HASH_KEY`. `seed_tenant.py` sai.
- **Alternatives considered**: migração de dados que cria a conexão da piloto com as variáveis atuais (acopla
  schema a segredos e quebra `downgrade`); manter fallback "empresa fixa" por um tempo (contradiz FR-001).

## R-16. Papel de controle e papel da aplicação

- **Decision**: a API e o worker conectam como `plantao_app` (RLS, sem `BYPASSRLS`). Os comandos de
  `scripts/tenants.py` que operam entre empresas usam `DATABASE_ADMIN_URL`. O papel administrativo precisa ignorar
  RLS (superusuário no Docker; `BYPASSRLS` em produção, documentado no runbook). Comandos que mexem em dados de
  uma empresa (documentos, avaliação) continuam usando `tenant_session` com o papel da aplicação.
- **Rationale**: é o padrão atual (`seed_tenant.py`). Teste de importação garante que nenhum módulo de `apps/`
  usa `database_admin_url`.
- **Alternatives considered**: papel `plantao_ops` dedicado com políticas (ver Complexity Tracking).

## R-17. Medir o critério de 2 horas (SC-001)

- **Decision**: `create` imprime o tempo de cada passo e o total em segundos, e o quickstart manda registrar o
  tempo manual do operador (edição do arquivo, geração de segredos, configuração da instância na Evolution) em
  uma tabela. O CLI só mede o que é automático; o restante é medido à mão em 2 criações seguidas.
- **Rationale**: o critério é de trabalho humano, não de CPU; a ferramenta ajuda mas não substitui a medição.

## R-18. Opt-in e escopo de contato

- **Decision**: `conversations.iniciada_por` com padrão `contato`; o worker só responde conversas em que a última
  mensagem é do lead (já é assim). Nenhum fluxo cria conversa com `empresa`; a coluna prepara o Sprint 4.
- **Rationale**: atende FR-030 sem inventar fluxo. Mensagem proativa fica fora de escopo (spec).

## R-19. Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| Evolution não envia `instance` ou headers por instância (R-02) | Webhook sem como resolver a empresa | Contingência com id de conexão na URL; teste de contrato isola o ponto em `parse_inbound` |
| Papel administrativo sem `BYPASSRLS` em produção (R-16) | Comandos do operador falham ao criar ou listar | Runbook e teste de integração com papel não superusuário que expõe o erro cedo |
| Reentrega de webhook durante a janela de transição da piloto (R-15) | Mensagens perdidas por 401 | Evolution reentrega; mensagens têm `external_id` único; runbook com ordem de deploy |
| Drenagem fixa de 120 s atrasa exclusão (R-11) | Operação mais lenta | Constante configurável; é um passo raro (US6, P3) |
| Estado lido do banco a cada mensagem (R-05) | Uma consulta a mais por mensagem | Consulta por chave primária; medir no teste de latência do webhook (< 500 ms) |
