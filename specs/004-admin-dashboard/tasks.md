---

description: "Lista de tarefas: Painel de operação de empresas (tenants)"
---

# Tasks: Painel de operação de empresas (tenants)

**Input**: documentos de design em `specs/004-admin-dashboard/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: INCLUÍDOS. A constituição exige teste de isolamento entre duas empresas em toda feature que toca dados
(princípio III), migração reversível, cobertura mínima de 80% em `core/` e testes escritos antes da implementação
(princípios V e VI). Em cada fase, as tarefas de teste vêm primeiro e devem **falhar** antes da implementação.

**Organization**: tarefas agrupadas por user story. Caminhos relativos a `plantao-ai/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivos diferentes, sem dependência pendente)
- **[Story]**: US1 a US5, conforme [spec.md](spec.md)
- Comando Python: `& ".venv\Scripts\python.exe" -m ...`; testes do front: `node --test apps/dashboard/web/tests`
- Restrições entre aspas (formatos, limites, nomes de colunas) vêm de [data-model.md](data-model.md) e
  [contracts/](contracts/) e não ficam a critério da implementação

## Prioridades e MVP

US1 e US2 são P1 e formam o **MVP de leitura**: o operador vê a carteira e abre a ficha, sem nenhuma escrita. US3 e US4 são
P2 (mudar estado; cadastrar e gerenciar empresas). US5 é P3 (conversas por metadados). A Fase 2 (fundação) é obrigatória
para todas: migração, papel de banco, autenticação, job de agregação e esqueleto do front.

US3 e US4 compartilham `apps/api/admin/escrita.py` (único módulo autorizado a importar `db.admin`); por isso US3 vem
antes e cria a base da escrita. US1, US2 e US5 só leem e podem avançar em paralelo depois da Fase 2.

**Portão antes de começar**: T008 (decisão sobre o ADR-0008, hoje "proposta"). A Fase 2 depende dele.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependência, configuração, fronteiras e esqueleto de pastas.

- [x] T001 Acrescentar `PyJWT[crypto]` a `requirements.txt` e regenerar `requirements.lock` e `requirements-dev.lock`; rodar `pip-audit` e registrar o resultado (justificativa: [research.md](research.md) R-06)
- [x] T002 Em `core/config.py` adicionar os campos `database_painel_url` (padrão `postgresql+asyncpg://plantao_painel:plantao_painel@localhost:5432/plantao`), `painel_db_password` (`plantao_painel`), `operadores` (`email:papel,email:papel`, papel `leitura` ou `operacao`; vazio = ninguém entra), `oidc_issuer`, `oidc_client_id`, `oidc_client_secret`, `oidc_redirect_uri`, `painel_auth_mode` (`oidc` ou `dev`; recusar `dev` se `env != "development"`), `painel_sessao_inatividade_min` (30), `painel_sessao_maxima_h` (12), `painel_limite_silencio_horas` (24), `painel_limite_handoff_pct` (30), `painel_limite_custo_pct` (90), `painel_escrita_por_minuto` (60); atualizar `.env.example` com cada variável comentada
- [x] T003 [P] Em `.importlinter` acrescentar o contrato `forbidden` "só apps.api.admin.escrita importa db.admin" (fontes: `apps` exceto `apps.api.admin.escrita`; proibido: `db.admin`) e garantir que `core.painel` não importa `apps`, `agents` nem `integrations`
- [x] T004 [P] Criar os pacotes com `__all__` explícito: `apps/api/admin/__init__.py`, `core/painel/__init__.py`, `tests/unit/painel/__init__.py`; criar as pastas vazias `apps/dashboard/web/{css,js/telas,assets,tests}`
- [x] T005 [P] Em `Makefile` acrescentar `test-web` (`node --test apps/dashboard/web/tests`), `painel-seed` (roda `scripts/painel_seed.py`) e `painel-dev` (API com `PAINEL_AUTH_MODE=dev`); incluir `test-web` na ajuda
- [x] T006 [P] Trazer para `apps/dashboard/web/assets/` as fontes Inter e Outfit e o Font Awesome Free (somente os ícones usados), auto-hospedados, e conferir a licença de cada arquivo antes de versionar (R-17). **Bloqueio conhecido**: a pasta `assets/` do design system original não existe no repositório; sem ela, usar os arquivos oficiais de cada projeto
- [x] T007 [P] Extrair os tokens e componentes do protótipo `design-system/plantao-admin.html` para `apps/dashboard/web/css/tokens.css`, `base.css` e `componentes.css`, **sem estilo inline** (compatível com a CSP de R-07); cobrir sidebar, topbar, cartão, KPI, pílulas, badge, tabela, barra de progresso, modal, toast e formulário; respeitar `prefers-reduced-motion`
- [x] T008 **Decisão do ADR-0008** (proposta): obter a aprovação do responsável pelo projeto em `docs/adr/0008-agregacao-do-painel.md` e trocar o status para "aceita" (ou registrar a alternativa escolhida e ajustar [plan.md](plan.md) e [data-model.md](data-model.md) antes de seguir)
- [x] T009 [P] Atualizar o docstring de `apps/dashboard/__init__.py` (hoje cita "Streamlit/Retool") para descrever o front-end estático em `web/` (ADR-0005)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: banco, papel restrito, autenticação, segurança HTTP, job de agregação e esqueleto do front.

**⚠️ CRITICAL**: nenhuma user story começa antes do fim desta fase.

### Testes da fundação (escrever primeiro; devem falhar)

- [x] T010 [P] `tests/integration/test_painel_privilegios.py`: com o papel `plantao_painel`, `has_column_privilege(..., 'SELECT')` é **falso** para `messages.conteudo`, `messages.external_id`, `conversations.contato_hash`, `conversations.contato_enc`, `tenant_knowledge.chunk_texto` e para toda coluna de `channel_credentials`; é **verdadeiro** para as colunas listadas em [data-model.md](data-model.md) §3.1; `INSERT`/`UPDATE`/`DELETE` negados em qualquer tabela
- [x] T011 [P] `tests/integration/test_painel_isolamento.py`: com duas empresas, `plantao_app` sob `tenant_session` de A não lê linha de B em `painel_agregado_hora` nem em `painel_situacao`; `plantao_painel` lê as duas; ampliar o teste de introspecção existente para exigir `tenant_id NOT NULL`, `FORCE ROW LEVEL SECURITY` e política de isolamento nas duas tabelas novas
- [x] T012 [P] `tests/integration/test_migracao_0005.py`: `upgrade` e `downgrade` da revisão `0005` são reversíveis e deixam o schema da `0004` intacto (inclui remover o papel `plantao_painel` e a coluna `tenants.versao`)
- [x] T013 [P] `tests/unit/painel/test_planos.py`: plano sem valor devolve "sem orçamento" e "margem indisponível" (nunca zero); `orcamento_pct = custo / orcamento * 100`; chave de plano desconhecida cai em `recepcionista`
- [x] T014 [P] `tests/unit/test_painel_auth.py`: sessão expira por inatividade (30 min deslizante) e no teto de 12 h; token guardado só como `sha256`; e-mail fora de `OPERADORES` é recusado; papel inválido na variável falha na inicialização; `id_token` com `iss`, `aud`, `nonce` ou assinatura errados é recusado (JWKS falso); `PAINEL_AUTH_MODE=dev` com `ENV != development` impede a aplicação de subir
- [x] T015 [P] `tests/contract/test_admin_seguranca.py`: sem sessão toda rota `/admin/*` (exceto `/admin/auth/*`) devolve 401 `nao_autenticado`; escrita com papel `leitura` devolve 403 `sem_permissao` e não altera o banco; `Origin` diferente do host devolve 403 `origem_invalida`; 61ª escrita no mesmo minuto devolve 429 `limite_excedido` com `Retry-After`; respostas de `/painel/*` têm `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `X-Frame-Options: DENY`; cookie `plantao_painel` com `HttpOnly; Secure; SameSite=Lax`
- [x] T016 [P] `tests/unit/painel/test_agregacao_pura.py`: baldes do histograma `≤1, 2, 3, 5, 8, 13, 21, 34, 55, 89, >89` segundos (11 posições), soma de histogramas, média `soma/n` e p95 estimado; início da hora em UTC; limites de "hoje" e do dia em `America/Sao_Paulo`
- [x] T017 [P] `tests/integration/test_painel_agregacao.py`: com duas empresas e mensagens, conversas, handoffs e `llm_calls` conhecidos, o job grava `painel_agregado_hora` e `painel_situacao` **iguais à contagem direta** (por remetente, `nao_texto`, handoffs, falhas de envio, tokens, custo por `finalidade` e por modelo, intenções); recalcular a mesma janela é idempotente; empresa A nunca recebe número de B; empresa com `dados_apagados_em` é ignorada; nenhuma coluna guarda texto ou contato

### Implementação da fundação

- [x] T018 Em `db/models.py` adicionar `Tenant.versao` (`int not null default 1`) e os modelos `PainelAgregadoHora` (PK `(tenant_id, hora)`; colunas `msgs_lead`, `msgs_agente`, `msgs_humano`, `msgs_nao_texto`, `conversas_iniciadas`, `handoffs`, `bloqueios_guardrail`, `falhas_envio`, `resp_n`, `resp_soma_ms`, `resp_hist` jsonb, `intencoes` jsonb, `tokens_entrada`, `tokens_saida`, `custo_usd numeric(14,6)`, `custo_roteador`, `custo_suporte`, `custo_embedding numeric(14,6)`, `custo_por_modelo` jsonb, `atualizado_em`) e `PainelSituacao` (PK `tenant_id`; `ultima_mensagem_em`, `ultimo_remetente`, `conversas_abertas`, `conversas_handoff`, `documentos`, `trechos`, `atualizado_em`), ambos com `tenant_id` FK `tenants.id` NOT NULL
- [x] T019 `db/migrations/versions/0005_painel.py` (`revision = "0005"`, `down_revision = "0004"`): adicionar `tenants.versao`; criar as duas tabelas e o índice em `(hora)`; criar o papel `plantao_painel` (`LOGIN PASSWORD` de `PAINEL_DB_PASSWORD`, `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`); `GRANT SELECT` por tabela/coluna exatamente como em [data-model.md](data-model.md) §3.1 (nunca `messages.conteudo`, `external_id`, `contato_*`, credenciais); `ENABLE` + `FORCE ROW LEVEL SECURITY` nas tabelas novas com política de isolamento por `app.tenant_id` e `CREATE POLICY painel_leitura ... FOR SELECT TO plantao_painel USING (true)` em cada tabela lida; `GRANT SELECT, INSERT, UPDATE, DELETE` das tabelas novas ao `plantao_app`; `downgrade` completo (T012)
- [x] T020 [P] `db/config_planos.py` com `PLANOS` (`recepcionista`, `recepcionista_agendador`, `pacote_completo`; cada um com `nome`, `orcamento_mensal_usd` e `preco_mensal_usd`, ambos opcionais) e `core/painel/planos.py` com `orcamento_do_plano`, `preco_do_plano`, `orcamento_pct`, `margem_estimada` (preço proporcional ao período menos custo; `None` sem preço). Os valores iniciais são definidos pelo negócio no PR; o código não inventa preços
- [x] T021 [P] `db/painel.py`: engine e `painel_session()` para `DATABASE_PAINEL_URL` (`NullPool` quando `env == "test"`), só leitura, sem `app.tenant_id`; `fechar_painel_engine()` chamada no `lifespan`; em `tests/conftest.py` definir `DATABASE_PAINEL_URL` do banco de teste e criar o papel/senha na sessão de testes
- [x] T022 `apps/api/admin/auth.py`: fluxo OIDC (código + PKCE, `state` e `nonce` em `painel:oidc:{state}` por 10 min), validação do `id_token` com `PyJWT` (assinatura por JWKS em cache curto, `iss`, `aud`, `exp`, `nonce`, e-mail verificado), lista `OPERADORES`, sessão opaca de 256 bits em `painel:sessao:{sha256(token)}` com expiração deslizante e teto, cookie `plantao_painel` (`HttpOnly; Secure; SameSite=Lax`), `PAINEL_AUTH_MODE=dev` com operador fixo, dependências `operador_atual`, `exigir_leitura`, `exigir_operacao`
- [x] T023 `apps/api/admin/seguranca.py`: verificação de `Origin` nas rotas que alteram estado, limite de taxa por operador (`painel:rl:{email}:{minuto}`, mesmo mecanismo de `apps/api/ratelimit.py`), cabeçalhos de segurança e CSP de `/painel/*`, `Retry-After` no 429
- [x] T024 `apps/api/admin/schemas.py`: erro padrão `{codigo, mensagem, campos}`, `Papel`, `Operador`, tipos comuns (`Periodo` = `hoje|7d|30d`) e handler que converte `ValidationError` em 400 `validacao` com mensagens em português **sem repetir valor de campo secreto**
- [x] T025 `apps/api/admin/__init__.py` exporta o `router`; em `apps/api/main.py` incluir o router `/admin`, montar `StaticFiles` de `apps/dashboard/web` em `/painel` (com os cabeçalhos de T023) e fechar o engine do painel no `lifespan`; rotas `GET /admin/auth/entrar`, `GET /admin/auth/retorno`, `POST /admin/auth/sair`, `GET /admin/eu`
- [x] T026 Logs: garantir em `core/observability/logging.py` os campos `operador`, `rota` e `empresa` (slug) no contexto das rotas `/admin`, **sem** corpo de requisição, credencial nem `Cookie` (teste em `tests/unit/test_logging.py` ampliado)
- [x] T027 `core/painel/agregacao.py`: `recalcular_empresa(tenant_id, desde, ate)` sob `tenant_session`, com upsert idempotente de `painel_agregado_hora` e `painel_situacao`, regras de [data-model.md](data-model.md) §2 e de [research.md](research.md) R-12 (histograma), R-15 (`bloqueios_guardrail` a partir de `handoff_log`, excluindo `falha_canal` e baixa confiança; `falhas_envio` = `messages.status_envio = 'falha'` do agente)
- [x] T028 `apps/worker/jobs.py` e `apps/worker/settings.py`: job `agregar_painel` registrado como cron **a cada 2 minutos** (janela: últimas 3 horas mais a hora corrente), execução diária que refaz os 2 últimos dias e apaga `painel_agregado_hora` com mais de **400 dias**; percorre as empresas uma a uma e registra duração e número de empresas no log
- [x] T029 `GET /admin/saude` em `apps/api/admin/leitura.py` e `POST /admin/atualizar` em `apps/api/admin/atualizar.py` (enfileira `agregar_painel` com trava `painel:atualizar:lock` de 20 s e no máximo uma por operador a cada 30 s; **não** importa `db.admin`); desatualizado se a idade passar de 10 minutos (503 `dados_desatualizados` em `/admin/saude`)
- [x] T030 Esqueleto do front: `apps/dashboard/web/index.html` (sem script nem estilo inline), `js/app.js`, `js/rotas.js` (hash `#/`, `#/empresas`, `#/empresas/nova`, `#/empresa/<slug>`, `#/empresa/<slug>/editar`, `#/empresa/<slug>/conversas`; rota desconhecida = "Empresa não encontrada"), `js/api.js` (fetch com cookie, 401 leva ao login e volta à tela de origem), `js/estado.js`, `js/escape.js` (função única de escape para todo dado vindo da API), `js/formatar.js` (números pt-BR, US$, "há X min", fuso `America/Sao_Paulo`), `js/telas/login.js`, componentes de carregando/vazio/erro/desatualizado, sidebar recolhível e topbar conforme [contracts/painel-ui.md](contracts/painel-ui.md)
- [x] T031 [P] `apps/dashboard/web/tests/escape.test.js` e `formatar.test.js` (`node --test`): nomes com `<`, `"` e `&` escapados; "há 3 min", "há 26 h", "sem mensagens"; moeda e milhares em pt-BR

**Checkpoint**: banco migrado, papel `plantao_painel` provado por teste, login e sessão funcionando, job de agregação gravando, front mostrando login e esqueleto.

---

## Phase 3: User Story 1 - Visão geral da carteira (Priority: P1) 🎯 MVP

**Goal**: o operador vê, numa tela, a saúde da carteira: totais por estado, mensagens, conversas, handoff, custo, funil, alertas e a tabela de empresas com última mensagem.

**Independent Test**: com 3 empresas em estados diferentes e mensagens conhecidas, abrir `#/` e conferir que cada número bate com a contagem direta na base (SC-003) e que cada empresa aparece com estado e última mensagem corretos.

### Tests for User Story 1 (escrever primeiro)

- [x] T032 [P] [US1] `tests/unit/painel/test_atencao.py`: sem atividade só para empresa `ativo` com mais de 24 h sem mensagem; handoff alto acima de 30% das conversas do período; custo alto em 90% ou mais do orçamento (plano sem orçamento nunca dispara); conexão não verificada; falhas de envio; limites lidos de `PAINEL_LIMITE_*`; empresa sem mensagens nunca quebra
- [x] T033 [P] [US1] `tests/integration/test_painel_visao_geral.py`: com duas empresas, `totais.*` = soma das duas; `anterior` usa o período de mesma duração imediatamente anterior; `empresas_por_estado` e `total`; funil e série diária no fuso de São Paulo; margem `disponivel = false` quando algum plano em uso não tem preço; `atencao` lista a empresa certa
- [x] T034 [P] [US1] `tests/contract/test_admin_leitura.py` (parte 1): formato de `/admin/visao-geral`, `/admin/empresas` e `/admin/planos`; `ordem` só aceita `nome, estado, mensagens, abertas, handoffs, ultima_mensagem, custo, orcamento, criada_em` (outro valor = 400); `tamanho` ≤ 100; `ultima_mensagem` nula quando não há mensagens; `/admin/empresas.csv` tem exatamente as colunas `slug, nome, nicho, plano, estado, criada_em, mensagens, conversas_abertas, handoffs, minutos_desde_ultima_mensagem, custo_usd`; **nenhuma** chave de resposta é `conteudo`, `contato*`, `segredo*`, `chave*`, `hash*` ou `external_id`
- [x] T035 [P] [US1] `apps/dashboard/web/tests/atencao.test.js` e `graficos.test.js`: arcos do donut somam a circunferência inteira; larguras do funil 100/64/42/24% (nenhuma abaixo de 20%); escala do eixo escolhe o menor passo que cobre o máximo; ordenação estável da tabela e ordem dos alertas por gravidade

### Implementation for User Story 1

- [x] T036 [US1] `core/painel/atencao.py`: motivos `sem_atividade`, `handoff_alto`, `custo_alto`, `conexao_nao_verificada`, `falhas_envio` e gravidade (funções puras, sem I/O)
- [x] T037 [US1] `core/painel/consultas.py`: `visao_geral(periodo)` e `listar_empresas(filtros)` via `painel_session()` sobre `painel_agregado_hora` e `painel_situacao`; período `hoje|7d|30d` em `America/Sao_Paulo`; ordenação por **whitelist**; busca por nome ou slug com parâmetros ligados (nunca texto no SQL); `exportar_csv` com as colunas fixas de T034
- [x] T038 [P] [US1] `apps/api/admin/schemas.py`: modelos de resposta de visão geral, item de lista, planos e erros de listagem
- [x] T039 [US1] `apps/api/admin/leitura.py`: `GET /admin/visao-geral`, `GET /admin/empresas`, `GET /admin/empresas.csv`, `GET /admin/planos` (todas exigem ao menos `leitura`, todas com `atualizado_em` por bloco)
- [x] T040 [P] [US1] `apps/dashboard/web/js/graficos.js`: linha (curvas suaves, área em gradiente, último ponto com marca fixa que só pulsa em escala e opacidade, reposicionada sem animar o trajeto ao trocar o período), donut (um `circle` por estado sobre a mesma circunferência, `stroke-dasharray` e `stroke-dashoffset` acumulados), funil em escala relativa por etapa, sparkline; `role="img"` com `aria-label`; sem animação com `prefers-reduced-motion`
- [x] T041 [US1] `apps/dashboard/web/js/telas/visao-geral.js`: 4 KPIs (Mensagens, Conversas, Taxa de handoff, Custo, com margem estimada ou "margem indisponível"), variação contra o período anterior com seta e texto, gráfico de linha, donut de estados, funil, "Atenção ao vivo" (vazio: "Nenhuma empresa precisa de atenção agora"), seletor `Hoje | 7d | 30d`, estados de carregando, vazio, erro por bloco e desatualizado
- [x] T042 [P] [US1] `apps/dashboard/web/js/telas/tabela-empresas.js`: tabela com busca, filtro por estado e nicho, ordenação por servidor, paginação de 25, ícone de atenção com texto alternativo, "sem mensagens" para empresa sem mensagens, botão `Exportar` (CSV do servidor com os filtros atuais)
- [x] T043 [US1] Topbar: "Atualizado há X" (texto simples), botão `Atualizar` (`POST /admin/atualizar`, consulta `/admin/saude` até mudar, desabilitado por 30 s, mostra "Atualizando...") e aviso de dados desatualizados acima de 10 minutos
- [x] T044 [US1] Responsividade e acessibilidade da visão geral: KPIs 4 → 2 → 1 colunas, sem rolagem horizontal da página em 390 px (a tabela rola dentro do cartão), foco visível, `<table>` com `<th scope>`, contraste AA (SC-008, FR-032)

**Checkpoint**: visão geral completa e conferida contra a base. Isoladamente já entrega valor (nenhuma escrita).

---

## Phase 4: User Story 2 - Ficha da empresa (Priority: P1)

**Goal**: o operador abre uma empresa e vê identificação, conexão, base de conhecimento, prontidão, atendimento, custo e auditoria.

**Independent Test**: abrir a ficha de uma empresa com histórico conhecido e conferir que os números batem com `tenants status` e com a base.

### Tests for User Story 2 (escrever primeiro)

- [x] T045 [P] [US2] `tests/integration/test_painel_ficha.py`: dados de identificação, estado e datas, conexão, documentos e trechos, última prontidão e último teste **iguais** aos de `tenants status`; atendimento e custo do período conferem com a base (por remetente, por conversa, por finalidade e por modelo, `por_conversa_usd`, p95); a ficha da empresa A não contém nenhuma linha da B
- [x] T046 [P] [US2] `tests/contract/test_admin_leitura.py` (parte 2): formato de `/admin/empresas/{slug}`, `/serie`, `/configuracao` e `/auditoria`; credenciais aparecem só como `"configuradas"` e, na auditoria, como `"<atualizada>"`; empresa com `dados_apagados_em` devolve `atendimento`, `custo` e `base` nulos; slug inexistente devolve 404 `empresa_nao_encontrada`; `acoes_permitidas` vem exatamente da tabela de transições de `core/tenancy/ciclo_vida.py`
- [x] T047 [P] [US2] `apps/dashboard/web/tests/ficha.test.js`: formatação de "dados apagados em <data>", "margem indisponível" (nunca zero) e do valor de credencial como "configuradas"

### Implementation for User Story 2

- [x] T048 [US2] `core/painel/consultas.py`: `ficha(slug, periodo)` (identificação, `versao`, conexão, base, prontidão, último teste, atendimento, custo, margem, `acoes_permitidas` a partir de `TRANSICOES`), `serie(slug, periodo)` (hora para `hoje`, dia para `7d`, 3 dias para `30d`), `configuracao(slug)` e `auditoria(slug, pagina)`, tudo via `painel_session()` filtrando por `tenant_id`
- [x] T049 [P] [US2] `apps/api/admin/schemas.py`: modelos de ficha, série, configuração e auditoria
- [x] T050 [US2] `apps/api/admin/leitura.py`: `GET /admin/empresas/{slug}`, `/serie`, `/configuracao`, `/auditoria`
- [x] T051 [US2] `apps/dashboard/web/js/telas/ficha.js`: cabeçalho (nome, badge, slug, nicho, plano, alertas), blocos de identificação e conexão, prontidão com ícones, atendimento, custo por finalidade e modelo com margem, gráficos, auditoria paginada; "dados apagados em <data>" quando aplicável; "Empresa não encontrada" com volta para a lista
- [x] T052 [P] [US2] Responsividade e acessibilidade da ficha (390 px sem rolagem horizontal, foco, contraste AA)

**Checkpoint**: US1 e US2 completas = **MVP de leitura** pronto para uso e demonstração.

---

## Phase 5: User Story 3 - Mudar o estado de uma empresa (Priority: P2)

**Goal**: suspender, retomar, encerrar e ativar pelo painel, só as transições permitidas, com confirmação e auditoria.

**Independent Test**: suspender uma empresa ativa; conferir o estado, a linha de auditoria com o e-mail do operador e o motivo, e que `tenants status` mostra "suspenso".

### Tests for User Story 3 (escrever primeiro)

- [x] T053 [P] [US3] `tests/integration/test_painel_estado.py`: suspender, retomar e encerrar gravam `audit_log` com `operador` = e-mail da sessão (nunca texto livre) e o motivo; `tenants.versao` incrementa; mensagem recebida após a suspensão não é respondida (reaproveitar o cenário da spec 002); ativar em `em_configuracao` com prontidão reprovada não ativa
- [x] T054 [P] [US3] `tests/contract/test_admin_estado.py`: `POST /admin/empresas/{slug}/estado`: fora da tabela = 409 `transicao_invalida` com `estado_atual` e `permitidos`; `encerrado` sem `confirmacao` igual ao nome exato = 400 `validacao`; prontidão reprovada = 409 `prontidao_reprovada` com `itens`; `versao` antiga = 409 `conflito_versao`; papel `leitura` = 403; `POST .../prontidao` devolve `{aprovada, itens}`
- [x] T055 [P] [US3] `apps/dashboard/web/tests/confirmacao.test.js`: o botão de encerrar só habilita com o nome **exato** (maiúsculas e espaços contam)

### Implementation for User Story 3

- [x] T056 [US3] `apps/api/admin/escrita.py` (base): único módulo de `apps/` que importa `db.admin`; dependência que abre **uma** transação administrativa por requisição, aplica a checagem de `versao`, incrementa `tenants.versao`, passa `operador` da sessão e devolve a ficha atualizada; conversão das exceções `TransicaoInvalida`, `ConexaoEmUso`, `ExclusaoRecusada` em erros do contrato
- [x] T057 [US3] `POST /admin/empresas/{slug}/estado` chamando `suspender`, `retomar`, `encerrar` e `ativar` de `core/tenancy` (nenhuma regra de transição reescrita no painel)
- [x] T058 [US3] `POST /admin/empresas/{slug}/prontidao` chamando `avaliar_prontidao`
- [x] T059 [US3] `apps/dashboard/web/js/telas/ficha.js` + `js/componentes/modal.js`: botões vêm de `acoes_permitidas`; janela modal com foco preso, `Esc` cancela, motivo opcional em Suspender e Encerrar, nome exato em Encerrar, lista de itens pendentes em `prontidao_reprovada`, tratamento de 409 `transicao_invalida` e `conflito_versao` (mostra o estado atual e recarrega), toast de sucesso; papel `leitura` não vê os botões e mostra "Papel de leitura: ações indisponíveis"

**Checkpoint**: operador muda o estado pelo painel; cada mudança aparece na auditoria da ficha e no CLI.

---

## Phase 6: User Story 4 - Cadastrar e gerenciar empresas (Priority: P2)

**Goal**: tela "Empresas" com lista de gestão e formulário de criação e edição (identificação, configuração, conexão, documentos), com o mesmo resultado do CLI.

**Independent Test**: criar uma empresa pelo formulário com o conteúdo de `docs/exemplos/empresa-modelo.yml` e conferir que o resultado equivale a `tenants create` (SC-009).

### Tests for User Story 4 (escrever primeiro)

- [x] T060 [P] [US4] `tests/integration/test_painel_cadastro_paridade.py`: criar pela API e por `criar_ou_continuar` com o mesmo conteúdo produz os mesmos campos, estado `em_configuracao` e linhas de auditoria equivalentes; repetir o `POST` em empresa existente em `em_configuracao` completa o que falta, sem duplicar
- [x] T061 [P] [US4] `tests/contract/test_admin_validacao.py`: `slug` fora de `^[a-z0-9]+(-[a-z0-9]+)*$` ou com mais de 63 caracteres = 400 com mensagem em `campos.slug`; `slug` repetido = 409 `slug_em_uso`; instância usada por outra empresa = 409 `instancia_em_uso`; `segredo_entrega` com menos de **32** caracteres = 400; `chave_envio` vazia = 400; horário fora de `HH:MM-HH:MM` ou `fechado` = 400; limite de desconto fora de 0 a 100, confiança fora de 0 a 1, mensagens por minuto fora de 1 a 600 e duração do handoff fora de 1 a 1440 = 400; a mensagem de erro **nunca** repete o segredo
- [x] T062 [P] [US4] `tests/integration/test_painel_edicao.py`: `PATCH` grava na auditoria **só** os campos alterados (valor anterior e novo, operador); sem alterações devolve `{alteracoes: 0}` e não mexe em `versao`; `slug` diferente = 400; empresa encerrada = 409 `empresa_encerrada`; empresa suspensa é editável sem mudar o estado; `PUT .../conexao` zera `verificada_em` e audita a marca `<atualizada>`; `versao` antiga = 409 `conflito_versao` com os valores atuais
- [x] T063 [P] [US4] `tests/contract/test_admin_credenciais.py`: nenhuma resposta, log capturado nem linha de auditoria contém `segredo_entrega`, `chave_envio` ou hash de credencial, em criação, edição e erros (SC-004, SC-010)
- [x] T064 [P] [US4] `tests/integration/test_painel_documentos.py`: até **10** arquivos de **2 MB** cada, só `.md` e `.txt` (`EXTENSOES_SUPORTADAS`); nome repetido na remessa = 400; formato inválido = 415; arquivo grande = 413; `POST` devolve 202 e a remessa termina com status por arquivo (`ok`, `inalterado`, `sem_texto`, `arquivo_grande`, `falha`) e contagem de documentos e trechos atualizada (LLM e embeddings falsos)
- [x] T065 [P] [US4] `apps/dashboard/web/tests/validar.test.js`: as mesmas regras de T061 em `validar.js` (slug, segredo, horário, faixas), sugestão de slug sem acento e com hífen, e erro apontando o **primeiro** campo inválido

### Implementation for User Story 4

- [x] T066 [US4] `apps/api/admin/schemas.py`: modelos de entrada de criação, edição, conexão e documentos reaproveitando `ConfigEmpresa` de `core/tenancy/config.py` (mesmas faixas e mensagens do CLI), com `Literal` para plano e nicho conhecidos
- [x] T067 [US4] `POST /admin/empresas` em `apps/api/admin/escrita.py` chamando `criar_ou_continuar` (idempotente), conexão opcional via `cadastrar_conexao`, resposta 201 com a ficha
- [x] T068 [US4] `PATCH /admin/empresas/{slug}` (diferença de campos, auditoria só do que mudou via `aplicar_alteracoes`, `versao`, recusa de empresa encerrada) e `PUT /admin/empresas/{slug}/conexao` (`cadastrar_conexao`, zera `verificada_em`)
- [x] T069 [US4] Documentos: `POST /admin/empresas/{slug}/documentos` (validação, bytes no Redis por 1 h em `painel:remessa:{id}`, enfileira `ingerir_remessa`, 202), job `ingerir_remessa` em `apps/worker/jobs.py` chamando `core.rag.ingest.ingerir_documento` por arquivo, e `GET /admin/empresas/{slug}/documentos/remessas/{id}`
- [x] T070 [P] [US4] `apps/dashboard/web/js/validar.js`: validação de formulário idêntica às regras do contrato (cliente), repetida pelo servidor; mensagens em português
- [x] T071 [US4] `apps/dashboard/web/js/telas/empresas.js`: lista de gestão (colunas Empresa, Nicho, Plano, Estado, Conexão, Documentos, Criada em, Ações), busca, filtro por estado, paginação, `Ver`, `Editar` (some para empresa encerrada e para papel `leitura`), botão `Nova empresa` só para `operacao`
- [x] T072 [US4] `apps/dashboard/web/js/telas/formulario.js`: blocos Identificação, Configuração, Conexão e Base de conhecimento; slug sugerido e somente leitura na edição; sete campos de horário; "Gerar" segredo de entrega (48 hexadecimais por `crypto.getRandomValues`) com alternar visibilidade; credenciais já cadastradas só como "configuradas" e "Substituir credenciais" explícito; lista de arquivos com remoção e recusa de formato, tamanho e nome repetido; resultado da remessa por arquivo; erros do servidor (`campos`) no próprio campo; foco no primeiro erro
- [x] T073 [US4] Conflito de edição simultânea na tela: em 409 `conflito_versao` mostrar os valores atuais e deixar escolher entre recarregar ou reaplicar; `beforeunload` e troca de rota perguntam antes de abandonar edição pendente; "Nenhuma alteração para salvar" sem chamar a API
- [x] T074 [P] [US4] (P3, FR-025) `GET /admin/empresas/{slug}/apagar-dados/resumo` e `POST .../apagar-dados` (só empresa `encerrada`, confirmação por nome exato, papel `operacao`) chamando `apagar_dados`, com o resumo do que será removido; teste em `tests/integration/test_painel_apagar.py` e botão na ficha de empresa encerrada

**Checkpoint**: cadastro e gestão completos, com resultado equivalente ao CLI.

---

## Phase 7: User Story 5 - Conversas por metadados (Priority: P3)

**Goal**: lista e detalhe de conversas só com metadados, sem texto de mensagem nem contato.

**Independent Test**: abrir uma conversa com texto e telefone conhecidos e conferir que nenhum dos dois aparece em tela, na resposta da API nem em log.

### Tests for User Story 5 (escrever primeiro)

- [x] T075 [P] [US5] `tests/contract/test_admin_conversas.py`: respostas de lista e detalhe não têm nenhum campo de texto nem de contato (nem mascarado); a lista traz `id_curto, id, canal, status, agente_atual, iniciada_em, ultima_atividade_em, total_mensagens`; o detalhe traz `handoff` (`motivo`, `confianca`, `em`) e a linha do tempo `{remetente, tipo, em, intencao, intencao_confianca, status_envio}`
- [x] T076 [P] [US5] `tests/integration/test_painel_conversas_privilegio.py`: uma consulta que tente `SELECT conteudo` ou `contato_enc` pelo `painel_session()` falha com "permission denied"; conversa da empresa B nunca aparece na empresa A

### Implementation for User Story 5

- [x] T077 [US5] `core/painel/consultas.py`: `listar_conversas(slug, pagina)` e `conversa(slug, id)` via `painel_session()`, selecionando **somente** as colunas liberadas (lista explícita, sem `SELECT *`)
- [x] T078 [US5] `apps/api/admin/leitura.py`: `GET /admin/empresas/{slug}/conversas` e `/{id}`; modelos pydantic **sem** campo de texto ou contato (o contrato proíbe acrescentá-los)
- [x] T079 [US5] `apps/dashboard/web/js/telas/conversas.js`: lista e detalhe com linha do tempo de metadados; nenhuma ação para ver o texto

**Checkpoint**: todas as histórias funcionais; nenhum caminho do painel expõe conteúdo ou contato.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T080 Em `core/tenancy/exclusao.py` incluir `PainelAgregadoHora` e `PainelSituacao` na lista de tabelas apagadas pelo `purge` e ampliar `tests/integration/test_exclusao.py` para provar que nada dessas tabelas sobra para a empresa apagada (R-18)
- [x] T081 [P] `scripts/painel_seed.py`: gera 3 a 50 empresas com histórico de 30 dias (mensagens, conversas, handoffs, `llm_calls`) e roda a agregação; usado por `make painel-seed` e pelo teste de carga
- [x] T082 [P] `tests/integration/test_painel_desempenho.py` (marcado como lento): com 50 empresas e cerca de 1 milhão de mensagens, `GET /admin/visao-geral` e `GET /admin/empresas/{slug}` respondem em até **3 s** (SC-002)
- [x] T083 [P] `docs/RUNBOOK_OPERACIONAL.md`: seção do painel (entrar, adicionar ou remover operador em `OPERADORES`, painel desatualizado e o que olhar, alterar planos por PR em `db/config_planos.py`, rotação da senha de `plantao_painel`) e alerta quando `GET /admin/saude` passar de 10 minutos
- [x] T084 [P] `README.md` e `.env.example`: novas variáveis, comandos `make painel-seed`, `make painel-dev`, `make test-web` e a URL `/painel/`
- [x] T085 [P] Revisão de segurança do painel (skill de revisão de segurança): CSP sem `unsafe-inline`, nenhum `innerHTML` sem escape, cookie, `Origin`, JWKS, limite de taxa, ausência de segredo em `localStorage` e na URL; registrar achados e correções
- [x] T086 [P] Checklist manual de acessibilidade e responsividade (teclado completo, foco preso nas janelas modais, contraste AA, `prefers-reduced-motion`, 390 px sem rolagem horizontal) em `specs/004-admin-dashboard/checklists/ui.md`
- [x] T087 Gates da definição de pronto: `make lint`, `make typecheck`, `make imports`, `make test`, `make test-web`, `make cov` (mínimo de **80%** em `core/painel`), `pip-audit` e `gitleaks` verdes; `.env.example` e docs atualizados; migração `0005` reversível
- [x] T088 Executar os 19 cenários de [quickstart.md](quickstart.md) com dados de `make painel-seed` e anotar o resultado de cada um; corrigir o que falhar
- [x] T089 [P] Reavaliar com dados reais o que ficou como interpretação: FR-044 (planos em arquivo versionado, [research.md](research.md) R-10), lista de motivos de guardrail (R-15) e necessidade de teste E2E de navegador (Complexity Tracking); registrar decisões em `research.md` ou em novo ADR

---

## Dependencies & Execution Order

### Ordem das fases

- **Phase 1 (Setup)**: sem dependência. T008 (ADR-0008) bloqueia a Phase 2.
- **Phase 2 (Fundação)**: depende da Phase 1. **Bloqueia todas as histórias.**
- **Phase 3 (US1)** e **Phase 4 (US2)**: dependem só da Phase 2 e podem andar em paralelo (US2 reaproveita a tabela e os gráficos de US1: T040 e T042 antes de T051).
- **Phase 5 (US3)**: depende da Phase 2 e de US2 (os botões ficam na ficha). Cria `escrita.py` (T056).
- **Phase 6 (US4)**: depende de US3 (T056) e da Phase 2; a lista de gestão reaproveita `tabela-empresas.js` (T042).
- **Phase 7 (US5)**: depende só da Phase 2 e de US2 (link na ficha).
- **Phase 8 (Polish)**: depois das histórias desejadas.

### Dentro de cada história

Testes (devem falhar) → modelos e consultas → API → front. Cada história termina num checkpoint testável sozinho.

### Oportunidades de paralelismo

- Phase 1: T003, T004, T005, T006, T007 e T009 em paralelo.
- Phase 2: todos os testes T010 a T017 e T031 em paralelo; depois T020, T021 em paralelo com T018/T019 (migração antes dos testes de banco passarem).
- US1: T032 a T035 em paralelo; T038, T040 e T042 em paralelo.
- US1 e US2 inteiras em paralelo entre si depois da fundação.
- US4: T060 a T065 em paralelo; T066 e T070 em paralelo.

### Exemplo de paralelismo (US1)

```text
Em paralelo:
  T032 test_atencao.py            T033 test_painel_visao_geral.py
  T034 test_admin_leitura.py      T035 atencao.test.js + graficos.test.js
Depois: T036 -> T037 -> T039   (back-end)    e    T040 + T042 (front, em paralelo) -> T041 -> T043
```

## Implementation Strategy

1. **MVP de leitura** = Phase 1 + 2 + US1 + US2. Entregável e demonstrável sozinho, sem nenhuma escrita, com o menor risco.
2. **Incremento 2** = US3 (mudar estado): começa a substituir comandos de operador.
3. **Incremento 3** = US4 (cadastro e gestão): substitui `tenants create` e `config set` para quem preferir a tela.
4. **Incremento 4** = US5 (conversas por metadados) e o polimento.
5. Em cada incremento: tarefas de teste primeiro, gates de T087 verdes e quickstart parcial executado antes de seguir.
6. Entregar em PRs pequenos, Conventional Commits, referenciando as tarefas (constituição, Fluxo de Desenvolvimento).

## Notes

- Total: 89 tarefas, todas concluídas. `[P]` = arquivos distintos e sem dependência pendente.
- Toda tarefa que toca dados tem teste de isolamento entre duas empresas (T011, T017, T033, T045, T076).
- Nenhuma tarefa cria, lê ou expõe texto de mensagem, contato, segredo ou hash de credencial no painel (T010, T063, T075, T076 garantem).
