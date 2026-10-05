# Sprint 3 — Resultados e limitações

Feature: [002-multitenancy](../specs/002-multitenancy/spec.md) (multi-tenancy real: onboarding, ciclo de vida, isolamento, exclusão de dados).

## 1. O que foi verificado automaticamente

Execução offline (LLM e WhatsApp simulados, Postgres e Redis reais via Docker):

| Verificação | Resultado |
|---|---|
| `pytest` | 596 testes passando |
| Cobertura total (`core`, `agents`, `db`, `apps`, `integrations`) | 94,95% (gate: 80%) |
| Cobertura de `core/guardrails` | 100% (gate: 100%) |
| `ruff check` | sem erros |
| `ruff format --check` | sem arquivos a reformatar |
| `mypy` (estrito, 79 arquivos) | sem erros |
| `lint-imports` | 4 contratos mantidos (inclui a camada `apps > agents > core > db`) |
| `pip-audit` | sem vulnerabilidades conhecidas |
| `gitleaks` (cópia do repositório sem `.venv`/`.git`) | 0 segredos no código versionado; os únicos achados foram o `.env` local (gitignorado, nunca commitado) e um valor curto de teste em [tests/unit/test_arquivo_empresa.py](../tests/unit/test_arquivo_empresa.py) usado só para validar a rejeição de segredo curto demais |
| `alembic downgrade 0003` seguido de `alembic upgrade head` | reversível, sem erros |
| Isolamento entre empresas (RLS) | suíte dedicada (`tests/integration/test_isolamento_*.py`), inclui uma quebra proposital de isolamento que falha a suíde de propósito (SC-003) |
| Papel administrativo restrito a `scripts/` | [tests/unit/test_admin_isolado.py](../tests/unit/test_admin_isolado.py), checagem estática por AST: nenhum arquivo em `apps/` importa `db.admin` nem `DATABASE_ADMIN_URL` |
| Exclusão de dados (SC-008) | [tests/integration/test_exclusao_dados.py](../tests/integration/test_exclusao_dados.py): purge de uma empresa zera 100% das linhas dela e não altera nenhuma linha de outra |
| Config por empresa com auditoria (SC-005) | [tests/integration/test_config_auditoria.py](../tests/integration/test_config_auditoria.py): alteração vale na próxima mensagem, sem reinício, e gera uma linha de auditoria por campo |

Linhas sem cobertura são majoritariamente código de composição que só roda com serviços reais (`apps/composition.py`, `apps/worker/settings.py`, o `lifespan` de `apps/api/main.py`) e ramos de erro de rede dos clientes externos.

## 2. Status das metas de sucesso (SC-001 a SC-010)

| Meta | Descrição resumida | Status |
|---|---|---|
| SC-001 | Onboarding completo (criar → ativar → responder) em até 2h, 2 vezes seguidas | **Pendente (T086)** — exige trabalho manual cronometrado com Evolution API real |
| SC-002 | 3 empresas ativas, 100% das respostas restritas aos próprios dados, 0% vazamento | **Pendente (T087)** — a suíte `run_evals --suite isolamento` existe, mas depende de `OPENROUTER_API_KEY` real |
| SC-003 | 100% dos cenários de isolamento passam; quebra proposital derruba a suíte | **Verificado automaticamente** — `tests/integration/test_isolamento_*.py`, incluindo [test_isolamento_quebra.py](../tests/integration/test_isolamento_quebra.py) |
| SC-004 | Suspensão para respostas em até 1 min; demais empresas mantêm SLA | **Verificado automaticamente** (efeito imediato, sem cache) — a medida de latência real (10 s, 90%) depende de carga real e fica para validação manual |
| SC-005 | Config vale na próxima mensagem em até 1 min, sem reinício; 100% com auditoria | **Verificado automaticamente** — efeito é síncrono (sem cache), confirmado em teste de integração |
| SC-006 | Empresa no limite de mensagens não afeta SLA das demais | **Verificado parcialmente** — o rate limit por empresa é isolado por chave Redis (`rl:{tenant_id}:...`), testado em `tests/integration`; a medida de SLA sob carga real fica para validação manual |
| SC-007 | Dados da empresa piloto preservados; metas do Sprint 2 continuam valendo | **Verificado automaticamente** — suíte completa do Sprint 2 (`tests/` de `001-router-support-agent`) continua passando dentro dos 596 testes |
| SC-008 | Exclusão remove 100% dos dados da empresa e 0% de outras | **Verificado automaticamente** — ver tabela acima |
| SC-009 | Gravar mensagem de uma empresa com credencial de outra é recusado em 100% dos casos | **Verificado automaticamente** — coberto em `test_isolamento_tenants.py`/`test_isolamento_quebra.py` (resolução por `instance_name` da conexão, não por credencial solta) |
| SC-010 | Ativação com prontidão incompleta é recusada em 100% das tentativas | **Verificado automaticamente** — `core/tenancy/prontidao.py` + testes de integração do fluxo `readiness`/`activate` |

## 3. O que ainda exige execução manual com serviços reais

- **T004 — Confirmação com Evolution API real.** Não executado nesta sessão (sem instância real disponível). Os três pontos (corpo de `messages.upsert` com `instance`, header de webhook por instância, `GET /instance/connectionState/{instance}`) permanecem como suposições de design registradas no ADR 0003; qualquer divergência exige ajuste em `integrations/whatsapp/client.py` e nas contingências de research R-02/R-10.
- **T085 — Quickstart ponta a ponta.** Seguir [quickstart.md](../specs/002-multitenancy/quickstart.md) (seções 1 a 9) com uma instância real da Evolution API e uma empresa de teste de verdade.
- **T086 — Medir SC-001.** Cronometrar 2 onboardings consecutivos (criação → prontidão → ativação → primeira resposta) e preencher a tabela da seção 3, passo 8, do quickstart.
- **T087 — Medir SC-002 com LLM real.** Rodar `python -m scripts.run_evals --suite isolamento --tenants a,b,c`, o que exige `OPENROUTER_API_KEY` com créditos.

Tabela a preencher após a execução real:

| Meta (spec) | Alvo | Medido |
|---|---|---|
| SC-001 (onboarding, 2 execuções) | ≤ 2h cada | pendente |
| SC-002 (isolamento com LLM real, 90 mensagens) | 100% restrito / 0% vazamento | pendente |
| SC-004 (SLA das demais empresas durante suspensão) | ≥ 90% em ≤ 10s | pendente |
| SC-006 (SLA das demais durante rate limit de uma empresa) | ≥ 90% em ≤ 10s | pendente |

## 4. Desvios e interpretações

- **Ordem de impressão do `purge` na CLI.** A ordem de exclusão no banco segue a ordem segura de chaves estrangeiras (`ORDEM_DE_EXCLUSAO`, começando por `repasses`/`HandoffLog`), mas o contrato da CLI documenta uma ordem de exibição começando por `conversas`. As duas preocupações foram separadas: `core/tenancy/exclusao.py` decide a ordem de apagar; `scripts/tenants.py` decide a ordem de exibir (constante `_ORDEM_DA_SAIDA`), mantendo as duas sem acoplamento.
- **`audit_log` não é apagado pelo purge.** A trilha de auditoria sobrevive propositalmente à exclusão de dados (inclusive ganha uma linha registrando a própria exclusão), para que SC-008 ("remove 100% das linhas dela") seja interpretado como as entidades de dado do cliente, não o histórico de auditoria da operação.
- **Testes escritos junto com o código.** Como no Sprint 2, não foi seguido o ciclo estrito red-green da constituição; a maior parte dos testes de US5 e US6 foi escrita e ajustada na mesma fase da implementação.

## 5. Limitações conhecidas

- **Um único canal e idioma seguem valendo**: WhatsApp via Evolution API e português do Brasil, herdado do Sprint 2.
- **Drenagem de `purge` fixa por configuração (`PURGE_DRENAGEM_SEGUNDOS`)**, não ajustável por empresa; qualquer SLA de drenagem diferenciado por contrato fica fora do escopo desta entrega.
- **`gitleaks` não está instalado localmente**; esta sessão usou a imagem Docker `zricethezav/gitleaks` contra uma cópia do repositório sem `.venv`/`.git`. Recomenda-se integrar o `gitleaks` ao pre-commit ou à pipeline de CI para varredura contínua.
- **T004, T085, T086 e T087 permanecem pendentes** por dependerem de credenciais e serviços reais (Evolution API, OpenRouter) não disponíveis neste ambiente de desenvolvimento automatizado.
