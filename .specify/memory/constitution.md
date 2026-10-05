# Plantão.AI Constitution

Plataforma multi-tenant de "funcionários digitais" (agentes de IA) via WhatsApp para PMEs
brasileiras. Contexto de negócio e técnico: `Projeto_Empresa_Autonoma.md`, seções 7 a 9.
Cada regra abaixo DEVE ser verificável em code review ou CI.

## Core Principles

### I. Stack e Linguagem
- Python 3.11+ com type hints obrigatórios em código de produção; mypy (ou pyright) em modo
  estrito para `core/`, `agents/` e `db/`.
- Stack fixa: FastAPI (async), SQLAlchemy 2 async, Postgres 16 + pgvector, Redis,
  LangGraph/LangChain, pydantic v2, pydantic-settings e httpx.
- LLMs DEVEM ser acessados somente via gateway OpenRouter, por uma camada única (`core/llm`).
  Nenhum módulo DEVE chamar SDK de provedor diretamente.
- Ruff (lint + format), pytest + pytest-asyncio e pre-commit são obrigatórios. Dependências
  DEVEM ter versões fixadas (lockfile) e ser auditadas com pip-audit.

*Justificativa: uma stack única e tipada reduz ambiguidade e evita lock-in de provedor de LLM.*

### II. Arquitetura Modular (Regra de Dependência)
Direção permitida das importações: `apps/` (api, worker, dashboard) → `agents/` → `core/` →
`db/`. `integrations/` implementa portas definidas em `core/`.
- `core/` NÃO DEVE importar de `apps/`, `agents/` ou `integrations/` (apenas Protocols próprios).
- `agents/` NÃO DEVE importar de `apps/`. Cada agente (router, sdr, scheduler, support,
  billing) é um pacote isolado com `agent.py`, `prompts/`, `tools/`, `schemas.py` e `tests/`.
- `integrations/` (whatsapp, calendar, payments) são adaptadores atrás de Protocols/ABCs;
  trocar Evolution API pela API oficial da Meta NÃO DEVE exigir mudança fora de
  `integrations/` e da configuração.
- Dependências DEVEM ser injetadas (construtor/`Depends`); NÃO DEVE haver estado global
  mutável nem singletons ocultos.
- Imports circulares são proibidos. A regra de dependência DEVE ser imposta no CI
  (import-linter ou equivalente).
- Cada módulo DEVE expor API pública explícita (`__all__`); importar internals de outro
  módulo é proibido.
- Agentes DEVEM ser máquinas de estado LangGraph com estado tipado (pydantic); transições
  DEVEM ser determinísticas e testáveis sem chamar LLM (LLM fake/mock).
- Webhooks NÃO DEVEM esperar o LLM: recebem, validam, enfileiram (Redis) e respondem 200
  rapidamente. O worker processa de forma idempotente (deduplicação por `message_id`).

*Justificativa: fronteiras impostas por ferramenta mantêm o código coeso e permitem trocar
canais, provedores e agentes sem efeito cascata.*

### III. Multi-tenancy e Isolamento de Dados (NON-NEGOTIABLE)
- Toda tabela de negócio DEVE ter `tenant_id NOT NULL`; toda query DEVE filtrar por `tenant_id`.
- Row-Level Security no Postgres DEVE ser a segunda camada de defesa; o tenant corrente é
  definido por sessão/transação, nunca por parâmetro livre.
- RAG, cache, filas e logs DEVEM ser particionados/namespaced por tenant. Dados de um tenant
  NÃO DEVEM entrar no contexto de outro.
- Toda feature que toca dados DEVE ter teste de isolamento entre dois tenants.

*Justificativa: um vazamento entre clientes é o pior incidente possível para o negócio e
para a LGPD.*

### IV. Segurança e Privacidade (LGPD)
- Segredos DEVEM vir apenas de variáveis de ambiente/secret manager. `.env` NÃO DEVE ser
  versionado; `.env.example` DEVE estar sempre atualizado; gitleaks DEVE rodar no pre-commit
  e no CI.
- Toda fronteira de entrada DEVE validar dados com pydantic; webhooks DEVEM verificar
  assinatura/token; DEVE haver rate limiting por tenant.
- Dados pessoais (telefone, nome) DEVEM ser criptografados em repouso; PII DEVE ser
  mascarada em logs e traces; retenção e exclusão sob demanda DEVEM ser previstas no design.
- Opt-in DEVE ser registrado antes do primeiro contato automatizado; mudanças de guardrails
  e handoffs DEVEM ter trilha de auditoria.
- Prompt injection é ameaça de primeira classe: conteúdo de usuário e documentos é sempre
  dado, nunca instrução; ferramentas dos agentes seguem privilégio mínimo; casos adversariais
  DEVEM ser testados antes de cada novo nicho entrar em produção.
- Falha segura: em dúvida, erro ou baixa confiança → handoff humano; o agente NÃO DEVE "chutar".

*Justificativa: o produto processa dados pessoais de terceiros e fala em nome do cliente.*

### V. Guardrails e Humano no Loop
- Toda resposta externa DEVE passar por `core/guardrails` antes do envio (tópicos proibidos,
  limite de preço/desconto, confiança mínima, palavras-gatilho como "Procon" e "processo").
- Agentes NÃO DEVEM inventar preços, prazos ou condições fora da base de conhecimento do tenant.
- Ações financeiras, contratuais, jurídicas ou irreversíveis DEVEM exigir aprovação humana.
- Todo guardrail crítico DEVE ter testes adversariais escritos antes da implementação
  (test-first: o teste falha, depois passa).

*Justificativa: erros de agente são responsabilidade legal do cliente e do CNPJ.*

### VI. Especificação Primeiro (SDD) e Qualidade
- Nenhuma feature DEVE ser implementada sem spec aprovada em `specs/NNN-nome/`
  (spec → clarify → plan → tasks → analyze → implement). Código que contradiz a spec exige
  atualizar a spec antes.
- Specs descrevem o quê e o porquê, sem stack; planos descrevem o como e DEVEM passar pelo
  "Constitution Check".
- Testes: unitários (sem rede, LLM fake), integração (Postgres/Redis via docker-compose) e
  contrato para `integrations/`. Cobertura mínima de 80% em `core/` e `agents/`, 100% em
  guardrails.
- Definition of Done: lint, type-check, testes, gitleaks e pip-audit verdes; docs e
  `.env.example` atualizados; migração Alembic reversível quando houver mudança de schema.

*Justificativa: a spec é a fonte da verdade e os gates automáticos mantêm a qualidade
constante com um time de uma pessoa.*

### VII. Observabilidade e Custo
- Logging estruturado (JSON) com `correlation_id`, `tenant_id` e `conversation_id`; conteúdo
  sensível NÃO DEVE ser logado sem mascaramento.
- Toda chamada de LLM DEVE registrar modelo, tokens, custo e latência por tenant
  (`usage_metrics`) desde o primeiro agente.
- DEVE haver orçamento e rate limit por tenant com alerta automático. Modelo barato para
  classificação/roteamento; modelo forte apenas para decisões críticas.
- Métricas-chave rastreadas: taxa de handoff, tempo de resposta, custo por conversa e margem
  por tenant.

*Justificativa: sem visibilidade de custo por tenant a margem de 70-80% não é garantível.*

### VIII. Simplicidade e Escopo
- MVP primeiro (YAGNI): NÃO DEVE haver abstração sem 2 usos reais ou sem fronteira de
  integração, nem microserviços, nem framework de agentes além do LangGraph.
- Toda decisão arquitetural relevante DEVE gerar um ADR curto em `docs/adr/`.
- Preferir biblioteca padrão e dependências já adotadas; nova dependência DEVE ser
  justificada no plano.

*Justificativa: o objetivo é validar o negócio rápido; complexidade não validada é custo.*

## Restrições Adicionais

- Migrações de schema DEVEM usar Alembic; migração já aplicada NÃO DEVE ser editada.
- Toda integração externa DEVE ter timeout, retry com backoff limitado e tratamento de erro
  explícito; falha de integração NÃO DEVE derrubar a conversa (degradar para handoff).
- O repositório DEVE manter estrutura coesa: `apps/`, `agents/`, `core/`, `integrations/`,
  `db/`, `tests/`, `infra/`, `docs/` e `specs/`. Novos diretórios de topo exigem ADR.

## Fluxo de Desenvolvimento e Qualidade

- Merge direto na `main` é proibido; PRs DEVEM ser pequenos, com Conventional Commits e
  histórico linear.
- CI DEVE bloquear merge se qualquer gate falhar: ruff, mypy, import-linter, pytest com
  cobertura mínima, pip-audit e gitleaks.
- Todo PR DEVE referenciar a spec/tasks de origem e declarar conformidade com esta
  constituição (ou exceção justificada).

## Governance

- Esta constituição prevalece sobre specs, planos e preferências individuais. Exceções
  DEVEM ser justificadas na seção "Complexity Tracking" do plano.
- Emendas seguem versionamento semântico: MAJOR remove/redefine princípio; MINOR adiciona
  princípio ou amplia orientação; PATCH esclarece redação. Cada emenda registra data e
  motivo no rodapé desta constituição e, se relevante, em um ADR (docs/adr/).
- A constituição DEVE ser revisada a cada sprint e antes de qualquer novo nicho ou tenant
  entrar em produção. Todo PR/review DEVE verificar conformidade.
- Decisão (2026-10-04): os gates dos princípios II, III, IV, V e VII são verificados pelo
  plano de cada feature na seção "Constitution Check"; os templates do Spec Kit não foram
  alterados.
- Decisão (002-multitenancy): `channel_connections` tem leitura aberta (sem filtro por
  `app.tenant_id`), porque o webhook precisa localizar a empresa pela instância do canal
  antes de qualquer sessão com tenant existir; é a única exceção reconhecida ao princípio
  III, documentada em [ADR-0003](../../docs/adr/0003-resolucao-por-conexao.md). A tabela não
  guarda credenciais (ficam em `channel_credentials`, com RLS normal e valores cifrados).
- Decisão (002-multitenancy): o papel administrativo do banco (`DATABASE_ADMIN_URL`, que
  ignora RLS) é de uso exclusivo de `scripts/` (migrações e CLI de operador: criar, listar,
  mudar estado, apagar empresa). Nenhum módulo de `apps/` DEVE referenciar esse papel; a
  checagem estática está em `tests/unit/test_admin_isolado.py`. A exclusão de dados de uma
  empresa (`purge`) está detalhada em
  [ADR-0004](../../docs/adr/0004-exclusao-de-dados-de-empresa.md).

**Version**: 1.0.1 | **Ratified**: 2026-10-04 | **Last Amended**: 2026-10-26
