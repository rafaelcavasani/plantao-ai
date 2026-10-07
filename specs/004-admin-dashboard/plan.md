# Implementation Plan: Painel de operação de empresas (tenants)

**Branch**: `004-admin-dashboard` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-admin-dashboard/spec.md`

## Summary

Dar ao operador da plataforma uma interface web para ver a saúde da carteira de empresas (visão geral e ficha),
mudar o estado de uma empresa e cadastrar e editar empresas, com o mesmo design system do protótipo
`design-system/plantao-admin.html`. O painel não muda regras de atendimento, ciclo de vida nem isolamento: ele as expõe.

Abordagem técnica (detalhes em [research.md](research.md)):

- **Front-end sem framework e sem build**: módulos ES, HTML e CSS puros em `apps/dashboard/web/`, servidos pela própria
  API em `/painel`. Gráficos em SVG próprio. Zero dependência de front-end nova; o protótipo já é a base visual.
- **API de operação** em `apps/api/admin/` (`/admin/*`), com pydantic em toda entrada. Leitura e escrita ficam em
  módulos separados; só o módulo de escrita pode abrir a sessão administrativa (contrato novo no import-linter).
- **Agregação por job, não por consulta pesada** ([ADR-0008](../../docs/adr/0008-agregacao-do-painel.md)): um job ARQ
  recalcula, empresa por empresa e **sob RLS**, a tabela `painel_agregado_hora` e a `painel_situacao`. A visão
  geral soma essas tabelas; atraso máximo de 5 minutos (FR-042). Botão "Atualizar" enfileira o job.
- **Papel de banco `plantao_painel`** ([ADR-0006](../../docs/adr/0006-leitura-entre-empresas-pela-api.md)): só
  `SELECT`, com privilégio por coluna que exclui `messages.conteudo`, `conversations.contato_*` e credenciais. O
  conteúdo de mensagem e o contato ficam fisicamente fora do alcance do painel (FR-004, FR-005).
- **Autenticação do operador** ([ADR-0007](../../docs/adr/0007-autenticacao-do-operador.md)): OIDC (código com PKCE),
  lista de operadores e papéis em variável de ambiente, sessão opaca no Redis com expiração por inatividade.
- **Escrita reaproveitando `core/tenancy/`**: criar, configurar, conexão, estado e prontidão chamam os mesmos
  serviços do `scripts/tenants.py`, com o e-mail do operador na auditoria. Concorrência otimista por
  `tenants.versao` (FR-040). Envio de documentos vira job ARQ que usa `core.rag.ingest`.
- **Planos** (orçamento e preço, FR-043 e FR-044) em `db/config_planos.py`, versionado no git. Limites de atenção
  em variáveis de ambiente (FR-012).

Fora do plano (spec): visão de cliente, cobrança, resposta manual de handoff, notificações, BI, i18n.

## Technical Context

**Language/Version**: Python 3.11 (API, worker, testes); JavaScript ES2022 nativo no navegador (sem transpilação).

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, ARQ/Redis, pydantic v2, httpx (todas já
adotadas). **Nova dependência de runtime**: `PyJWT[crypto]` para validar o `id_token` do provedor OIDC (justificada em
[research.md](research.md) R-06; `cryptography` já está no projeto). Nenhuma biblioteca de front-end.

**Storage**: PostgreSQL 16 (migração `0005_painel`: coluna `tenants.versao`, tabelas `painel_agregado_hora` e
`painel_situacao`, papel `plantao_painel`); Redis 7 (sessões, estado OIDC, limite de taxa, resultado de remessas de
documentos).

**Testing**: pytest + pytest-asyncio (unitários sem rede, integração com Postgres/Redis do docker-compose, contrato da
API `/admin/*`); `node --test` (nativo do Node 18, sem dependência) para as funções puras do front-end (validação de
formulário, formatação, regras de atenção); teste de isolamento com duas empresas e teste de privilégio de coluna do
papel `plantao_painel`. Teste visual/E2E fica fora desta versão (ver Complexity Tracking).

**Target Platform**: Linux server em produção; Windows + Docker Desktop em desenvolvimento; navegadores atuais
(Chrome, Edge, Firefox, Safari), celular e tablet para as telas de leitura (SC-008).

**Project Type**: web-service (API + worker) com front-end estático servido pela API, dentro de `apps/dashboard/`.

**Performance Goals**: visão geral em até 3 s com 50 empresas e 1 milhão de mensagens (SC-002); ficha em até 3 s com 100
mil mensagens; atraso dos números ≤ 5 min (FR-042).

**Constraints**: nenhuma resposta, log ou tela com texto de mensagem, contato, segredo ou hash de credencial
(SC-004); toda escrita auditada com o e-mail do operador (SC-005); sessão expira por inatividade (FR-006).

**Scale/Scope**: 1 a 5 operadores, dezenas a poucas centenas de empresas; 4 telas principais (visão geral, empresas,
ficha, formulário) mais login; ~20 endpoints.

## Constitution Check

*GATE: passa antes da pesquisa e é reavaliado depois do desenho (seção ao final).*

| Princípio | Avaliação |
|---|---|
| I. Stack e linguagem | Python/FastAPI/SQLAlchemy/Redis mantidos. Front-end em JS puro (a constituição não fixa stack de front). Uma dependência Python nova (`PyJWT`), justificada. mypy estrito vale para o código novo em `core/` e `db/`. |
| II. Arquitetura modular | `apps/api/admin` → `core/painel`, `core/tenancy` → `db`. Nada de `core` importando `apps`. Contrato novo no import-linter: só `apps.api.admin.escrita` importa `db.admin`. Dependências injetadas por `Depends`. |
| III. Multi-tenancy (NON-NEGOTIABLE) | Tabelas novas têm `tenant_id NOT NULL`, RLS forçado e política de leitura própria para `plantao_painel`. O job de agregação roda sob `tenant_session`. Leitura entre empresas é exceção documentada (ADR-0006/0008), limitada a agregados e metadados por privilégio de coluna. Teste de isolamento com duas empresas obrigatório. |
| IV. Segurança e LGPD | Sem PII no painel por construção (privilégio de coluna). Segredos só por ambiente. Entrada validada com pydantic. Sessão `HttpOnly`/`Secure`/`SameSite`, verificação de `Origin`, limite de taxa por operador. Auditoria de toda escrita. |
| V. Guardrails e humano no loop | Ações irreversíveis (encerrar, apagar dados) exigem confirmação digitando o nome (FR-007). O painel não responde conversas. |
| VI. Spec primeiro | Spec 004 aprovada e clarificada. Cobertura mínima de 80% em `core/`; testes escritos antes da implementação em `tasks.md`. |
| VII. Observabilidade e custo | Logs JSON com `operador`, `correlation_id`, `tenant_id`; sem conteúdo sensível. O painel é a primeira leitura de custo por empresa; o job de agregação usa `llm_calls`. |
| VIII. Simplicidade | Sem framework de front, sem build, sem biblioteca de gráfico, sem tabela de operadores. Três ADRs (0005 a 0007 aceitas) e um novo (0008, proposta). |

Resultado: **passa**, com três itens em Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/004-admin-dashboard/
├── plan.md              # Este arquivo
├── research.md          # Fase 0: decisões e alternativas
├── data-model.md        # Fase 1: tabelas, privilégios, estado em Redis
├── quickstart.md        # Fase 1: como validar ponta a ponta
├── contracts/
│   ├── admin-api.md     # Endpoints /admin/*, erros e códigos
│   └── painel-ui.md     # Rotas, telas, estados e regras de interface
└── tasks.md             # Fase 2 (/speckit-tasks): NÃO criado aqui
```

### Source Code (repository root)

```text
apps/
├── api/
│   ├── main.py                       # monta /admin e /painel (StaticFiles)
│   └── admin/                        # NOVO
│       ├── __init__.py               # API pública: router
│       ├── auth.py                   # OIDC, sessão no Redis, papéis
│       ├── seguranca.py              # Origin, limite de taxa, cabeçalhos (CSP)
│       ├── schemas.py                # modelos pydantic de entrada e saída
│       ├── leitura.py                # GET /admin/* (usa db.painel)
│       └── escrita.py                # POST/PATCH /admin/* (único a importar db.admin)
├── worker/
│   └── jobs.py                       # + agregar_painel (cron) e ingerir_remessa
└── dashboard/
    └── web/                          # NOVO: front-end estático
        ├── index.html
        ├── css/ (tokens.css, base.css, componentes.css)
        ├── js/ (app.js, api.js, rotas.js, estado.js, formatar.js, validar.js, atencao.js,
        │        graficos.js, telas/{visao-geral,empresas,ficha,formulario,login}.js)
        ├── assets/ (fontes e ícones auto-hospedados)
        └── tests/ (node --test)
core/
└── painel/                           # NOVO
    ├── __init__.py
    ├── agregacao.py                  # recalcula painel_* de uma empresa (sob RLS)
    ├── consultas.py                  # leituras agregadas e de ficha (via sessão do painel)
    ├── atencao.py                    # regras de alerta (puras)
    └── planos.py                     # orçamento e preço por plano
db/
├── painel.py                         # NOVO: engine e sessão do papel plantao_painel
├── config_planos.py                  # NOVO: plano → orçamento e preço (US$)
├── models.py                         # + PainelAgregadoHora, PainelSituacao, Tenant.versao
└── migrations/versions/0005_painel.py
tests/
├── unit/painel/                      # atenção, planos, agregação pura, schemas
├── integration/test_painel_*.py      # isolamento, privilégios, agregação, escrita, auditoria
└── contract/test_admin_api.py
docs/
├── adr/0008-agregacao-do-painel.md
└── RUNBOOK_OPERACIONAL.md            # + seção do painel
```

**Structure Decision**: o front-end mora em `apps/dashboard/web/` (ADR-0005), sem diretório de topo novo. O código
Python novo se divide em `apps/api/admin` (borda HTTP), `core/painel` (regra e consulta, testável sem HTTP) e
`db/painel.py` (acesso do papel restrito). A escrita não ganha serviço novo: reutiliza `core/tenancy/*` e
`core/rag/ingest`.

## Complexity Tracking

| Violação ou custo | Por que é necessário | Alternativa mais simples descartada porque |
|---|---|---|
| Papel de banco `plantao_painel` e política de leitura entre empresas (exceção ao princípio III) | A visão geral soma todas as empresas; precisa ler entre empresas sem papel administrativo no processo web | Ler empresa por empresa com `tenant_session` não soma no banco e daria à API acesso ao conteúdo das mensagens |
| Job de agregação + duas tabelas novas | Cumprir SC-002 (3 s com 1 milhão de mensagens) e FR-042 (≤ 5 min) sem pesar no banco do atendimento | Consulta direta em `messages`/`llm_calls` a cada abertura: lenta e disputa recursos com o atendimento |
| Nova dependência `PyJWT[crypto]` | Validar assinatura do `id_token` OIDC (obrigatório para a identidade real, ADR-0007) | Validar JWT à mão com `cryptography`: mais código de segurança próprio e mais risco |
| Teste de navegador fora do CI | `scripts/painel_e2e/` roda Chrome real (`playwright-core`, `axe-core`) e `jsdom` sob demanda, com as dependências instaladas só naquela pasta | Colocar Playwright no CI e no `package.json` do projeto: dependência e infraestrutura que ainda não se pagam para 4 telas; reavaliar quando a interface crescer |

## Pós-desenho: Constitution Check (reavaliação)

O desenho de [data-model.md](data-model.md) e [contracts/](contracts/) confirma os resultados acima. Pontos que mudaram
em relação à primeira avaliação:

- A leitura de **ficha** não usa `tenant_session`: usa o papel `plantao_painel` filtrando por `tenant_id`, para que o
  privilégio de coluna garanta a ausência de conteúdo e contato também ali (ADR-0006).
- `FR-044` ("alteração auditada") é atendido pelo histórico do git sobre `db/config_planos.py` (research R-10). Se a
  intenção era uma trilha dentro do painel, isso vira um acréscimo (tabela `planos` e linha de auditoria global).
- Abertos para a implementação (não bloqueiam o plano): origem exata de "bloqueio por guardrail" (research R-15) e
  provedor OIDC definitivo (Google é o assumido).
