# Runbook operacional — Plantão.AI

Guia único para quem nunca viu o projeto: instalar do zero, subir a aplicação, cadastrar uma empresa, operar o
dia a dia e resolver os problemas mais comuns. Todos os comandos abaixo partem da pasta `plantao-ai/` e usam
PowerShell (Windows). Em Linux/macOS, troque `.venv\Scripts\Activate.ps1` por `source .venv/bin/activate` e
`Copy-Item` por `cp`.

Para o fluxo de **incidente** (pausar/retomar uma empresa específica), use o
[RUNBOOK_INCIDENTE.md](RUNBOOK_INCIDENTE.md). Este documento cobre tudo o mais: instalação, configuração,
execução, onboarding, operação contínua e qualidade.

## 1. O que é a aplicação

Núcleo multi-tenant de agentes de IA que atendem clientes finais de pequenas e médias empresas via WhatsApp.

```
WhatsApp -> webhook (FastAPI) -> fila (arq/Redis) -> worker
         -> guardrails de entrada -> Roteador -> Suporte (RAG) -> guardrails de saída
         -> resposta ao cliente OU handoff para humano
```

- **API** (FastAPI): recebe o webhook do WhatsApp, valida, persiste e enfileira. Não chama LLM.
- **Worker** (arq): consome a fila, roda o grafo de agentes (LangGraph), grava a decisão e envia a resposta.
- **Roteador**: classifica a intenção da mensagem (modelo barato).
- **Suporte**: responde só com base nos documentos do tenant (RAG com pgvector), cita trechos e calcula confiança.
- **Guardrails** de entrada e saída: PII, injeção de prompt, valores não fundamentados, promessas proibidas, limite de desconto.
- **Multi-tenancy**: isolamento por Row-Level Security no Postgres; cada empresa tem seu próprio canal, configuração e dados.

Diagramas completos (sequência da mensagem, grafo do orquestrador, modelo de dados) estão no
[README.md](../README.md#arquitetura-e-funcionamento).

## 2. Pré-requisitos

| Ferramenta | Versão | Uso |
|---|---|---|
| Python | 3.11+ | API, worker, CLIs |
| Docker + Docker Compose | qualquer recente | Postgres 16 (pgvector) e Redis |
| make | Chocolatey no Windows, nativo em Linux/macOS | atalhos do [Makefile](../Makefile) |
| git | qualquer recente | clonar o repositório |
| Chave de API da OpenRouter | — | chat e embeddings (obrigatória para respostas reais) |
| Instância da Evolution API | — | canal WhatsApp (self-hosted); dispensável para testar API/worker localmente com o canal simulado dos testes |

`make` é opcional: todo alvo do Makefile tem o comando Python equivalente documentado nas seções abaixo.

## 3. Instalação do zero

```powershell
git clone <url-do-repositorio>
cd plantao-ai

docker compose up -d          # Postgres (pgvector) na 5432, Redis na 6379
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Verifique que os containers subiram:

```powershell
docker compose ps
```

## 4. Variáveis de ambiente

```powershell
Copy-Item .env.example .env
```

Gere os segredos obrigatórios e cole no `.env`:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # PII_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                # PII_HASH_KEY
```

| Variável | Obrigatória | Observação |
|---|---|---|
| `DATABASE_URL` | sim | papel `plantao_app`, sujeito a RLS. Usada pela API e pelo worker. |
| `DATABASE_ADMIN_URL` | sim | dono do banco. Usada só por `alembic` e por `scripts/` (CLI do operador). **Nunca** na API/worker. |
| `APP_DB_PASSWORD` | sim | senha do papel `plantao_app`, criado pela migração. |
| `REDIS_URL` | sim | fila do arq e rate limit. |
| `OPENROUTER_API_KEY` | sim para respostas reais | chat e embeddings. |
| `MODEL_CHEAP`, `MODEL_STRONG`, `EMBEDDING_MODEL` | não | padrões em `.env.example`. |
| `PII_ENCRYPTION_KEY` | sim | Fernet; cifra o telefone do contato. A aplicação recusa subir sem ela. |
| `PII_HASH_KEY` | sim | HMAC; permite localizar a conversa pelo telefone sem descriptografar. |
| `WHATSAPP_BASE_URL` | sim | URL da Evolution API. A instância, a chave de envio e o segredo de entrega são **por empresa** (ver onboarding, seção 6), nunca globais. |
| `PURGE_DRENAGEM_SEGUNDOS` | não | espera entre encerrar e apagar os dados de uma empresa (padrão 120s). |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | não | traces; só ativa se houver chave. |

Sem `PII_ENCRYPTION_KEY` ou `PII_HASH_KEY` a API falha na subida com
`RuntimeError: Variáveis de ambiente obrigatórias ausentes`.

## 5. Migrações do banco

```powershell
make migrate
# equivalente: python -m alembic upgrade head
```

Cria o schema, o papel `plantao_app` (sem superusuário, sem `BYPASSRLS`) com as políticas de RLS, e os índices
pgvector. Para recriar o banco do zero (apaga volumes):

```powershell
make reset-db
```

Para gerar uma nova migração a partir de mudanças nos modelos:

```powershell
make migration MSG="descricao da mudanca"
```

## 6. Subir a aplicação

Dois processos, cada um em um terminal (ambos com o venv ativado):

```powershell
make api        # uvicorn apps.api.main:app --reload --port 8000
make worker      # arq apps.worker.settings.WorkerSettings
```

Confirme que a API está no ar:

```powershell
curl http://localhost:8000/health
# {"status":"ok","service":"plantao-ai"}
```

O webhook do WhatsApp é `POST /webhooks/whatsapp`, autenticado pelo header `X-Webhook-Token`, comparado com o
segredo **daquela conexão** (não existe segredo global). A empresa é resolvida pelo `instance_name` do payload,
não por um tenant fixo.

## 7. Onboarding de uma empresa (tenant)

Não existe seed de tenant único: cada empresa entra por um arquivo de onboarding sem segredos — as credenciais
são referenciadas por **nome de variável de ambiente**. Esquema completo:
[onboarding-file.md](../specs/002-multitenancy/contracts/onboarding-file.md). Exemplo pronto:
[docs/exemplos/empresa-modelo.yml](exemplos/empresa-modelo.yml).

### 7.1 Preparar o arquivo e as credenciais

Copie `docs/exemplos/empresa-modelo.yml`, ajuste `slug`, `nome_empresa`, `nicho`, `configuracao` e `canal`
(`instance_name` deve ser único em toda a plataforma). Exporte as credenciais referenciadas pelo arquivo:

```powershell
$env:MINHA_CLINICA_API_KEY = "..."
$env:MINHA_CLINICA_WEBHOOK_SECRET = "..."   # >= 32 caracteres
```

### 7.2 Criar, verificar e ativar

```powershell
python -m scripts.tenants create    --file docs\exemplos\empresa-modelo.yml --operador rafael
python -m scripts.tenants readiness minha-clinica --operador rafael
python -m scripts.tenants test       minha-clinica --file docs\exemplos\empresa-modelo.yml --operador rafael
python -m scripts.tenants activate   minha-clinica --operador rafael
```

- `create`: idempotente — repetir não duplica nada; empresa já ativa continua ativa. Avança em 6 passos
  (empresa, configuração, conexão, credenciais, documentos, resumo) e termina em `em_configuracao`.
- `readiness`: avalia 4 itens (configuração completa, documentos indexados, conexão verificada, conversa de
  teste aprovada) e grava o resultado. Reprovado lista as pendências, uma por linha.
- `test`: roda a pergunta/resposta esperada do arquivo (`teste_prontidao`) contra o agente de verdade.
- `activate`: reavalia a prontidão; se aprovada, muda para `ativo`; senão recusa (saída de código `1`) e lista o
  que falta.

### 7.3 Ingestão de documentos (base de conhecimento)

Se o arquivo de onboarding referenciar uma pasta (`documentos.pasta`), o `create` já ingere. Para gerenciar depois:

```powershell
make ingest TENANT=minha-clinica DOCS=caminho\para\pasta
# ou:
python -m scripts.ingest_docs load   --tenant minha-clinica caminho\para\pasta
python -m scripts.ingest_docs list   --tenant minha-clinica
python -m scripts.ingest_docs remove --tenant minha-clinica nome-do-arquivo.md --yes
```

Formatos aceitos: `.md`, `.txt`, `.pdf` (até 5 MB). Cada documento é dividido em trechos de 800 caracteres (overlap
100), embeddings calculados fora da transação, e a troca de versão é atômica (documento novo entra inteiro ou o
anterior permanece). Conteúdo do arquivo nunca é logado.

### 7.4 Comandos de consulta e configuração

```powershell
python -m scripts.tenants list
python -m scripts.tenants status minha-clinica
python -m scripts.tenants config show minha-clinica
python -m scripts.tenants config set  minha-clinica --operador rafael limite_desconto_percentual=5
python -m scripts.tenants audit       minha-clinica
```

`config set` valida todos os campos juntos: se um for inválido, **nada é salvo** e cada erro é listado com o
valor anterior preservado. Mudança vale na próxima mensagem, sem reiniciar API/worker. Toda alteração grava
`audit_log` (campo, valor anterior, valor novo, operador, data).

## 8. Operação do dia a dia (ciclo de vida da empresa)

Estados possíveis: `em_configuracao -> ativo <-> suspenso`, `ativo/suspenso -> encerrado` (definitivo).

```powershell
python -m scripts.tenants suspend minha-clinica --operador rafael --motivo "texto curto"
python -m scripts.tenants resume  minha-clinica --operador rafael
python -m scripts.tenants close   minha-clinica --operador rafael --motivo "texto curto"
python -m scripts.tenants purge   minha-clinica --operador rafael --confirmar "Nome Exato da Empresa"
```

- **Suspender**: efeito em até 1 minuto. Mensagem nova recebe `200 {"status":"suspended"}` e não é enfileirada;
  job já enfileirado é descartado (`empresa_inativa`); demais empresas não são afetadas.
- **Retomar**: mensagens novas voltam a ser respondidas; as recebidas durante a suspensão **não** são
  reprocessadas (ficam marcadas `recebida_em_suspensao` no histórico).
- **Encerrar**: estado definitivo; dados continuam no banco até o `purge`.
- **Apagar (`purge`)**: só após `PURGE_DRENAGEM_SEGUNDOS` do encerramento e com o nome exato da empresa como
  confirmação; apaga conversas, mensagens, documentos, trechos, usos, repasses, credenciais, conexão e
  configuração — mantendo o `audit_log` e liberando o `instance_name` para reuso. Contagens impressas são só
  números, sem dado pessoal.

Passo a passo detalhado de investigação de incidente (o que acontece em cada camada durante a suspensão, ordem
segura de deploy de migrações multi-tenant, uso do papel administrativo em produção) está no
[RUNBOOK_INCIDENTE.md](RUNBOOK_INCIDENTE.md).

## 9. Observabilidade

| O quê | Onde | Para quê |
|---|---|---|
| `llm_calls` (tabela) | Postgres | finalidade, modelo, tokens, custo USD, latência e erro de cada chamada ao OpenRouter, inclusive falhas. |
| `audit_log` (tabela) | Postgres | toda mudança de configuração, estado, conexão e exclusão de dados: campo, valor anterior, novo, operador, data. |
| `handoff_log` (tabela) | Postgres | motivo de cada repasse para humano, por conversa. |
| Logs da aplicação | stdout (JSON) | `correlation_id`, `tenant_id`, `conversation_id`; telefone e mensagem mascarados; nunca payload de webhook nem credenciais. |
| LangSmith | externo, opcional | traces do grafo, só se `LANGSMITH_API_KEY` estiver definida. |

Motivos de `handoff_log.motivo`: `nao_texto`, `mensagem_vazia`, `palavra_gatilho:<termo>` (guardrails de
entrada); `intencao_sem_agente:<intencao>` (roteador); `sem_resposta_na_base` (suporte sem trecho relevante);
`falha_llm`, `falha_embedding` (erro/timeout/JSON inválido do OpenRouter); `confianca_abaixo_do_minimo`,
`topico_proibido:<termo>`, `desconto_acima_do_limite`, `valor_nao_fundamentado:<valor>` (guardrails de saída).

## 10. Testes e qualidade

```powershell
make test               # suite completa
make test-unit          # sem Postgres nem Redis
make test-integration   # exige docker compose up
make test-adversarial   # casos de segurança
make cov                # cobertura: 80% total, 100% em core/guardrails
make lint               # ruff check + format --check
make format             # ruff check --fix + format
make typecheck          # mypy estrito
make imports             # contratos de camada (import-linter)
make audit               # pip-audit
make check               # lint + typecheck + imports + cov + audit (gate completo)
```

Testes de integração exigem Postgres/Redis do `docker compose`; o banco `plantao_test` é recriado a cada
sessão. Hooks de commit: `pre-commit install -c plantao-ai/.pre-commit-config.yaml` (a partir da raiz do
repositório). CI em `.github/workflows/ci.yml`.

## 11. Avaliação com LLM real

```powershell
python -m scripts.run_evals --tenant minha-clinica --suite todas
# ou: make evals TENANT=minha-clinica SUITE=todas
```

Mede acerto de roteamento, groundedness, taxa de handoff, robustez adversarial, latência e custo. Exige
`OPENROUTER_API_KEY` válida e **consome créditos**. Resultados e limitações de cada sprint:
[SPRINT_2_RESULTADOS.md](SPRINT_2_RESULTADOS.md), [SPRINT_3_RESULTADOS.md](SPRINT_3_RESULTADOS.md).

## 12. Problemas comuns

| Sintoma | Causa provável | Como resolver |
|---|---|---|
| API não sobe: `Variáveis de ambiente obrigatórias ausentes` | `PII_ENCRYPTION_KEY`/`PII_HASH_KEY` vazias no `.env` | Gerar com os comandos da seção 4 e preencher o `.env`. |
| Webhook devolve `401` | Instância desconhecida, sem conexão cadastrada, ou `X-Webhook-Token` errado | Confirmar `instance_name` e segredo da conexão com `scripts.tenants status <slug>`; recriar a conexão com `tenants create` se necessário. |
| Webhook devolve `200 {"status":"suspended"}` | Empresa suspensa | `python -m scripts.tenants resume <slug> --operador <nome>` (ver seção 8). |
| Consulta ao banco devolve zero linhas inesperadamente | RLS ativo sem `app.tenant_id` definido na sessão | Usar `tenant_session`/`admin_session` corretos; nunca consultar fora desses contextos. |
| `scripts.tenants`/`ingest_docs` não enxerga outras empresas | Faltou `DATABASE_ADMIN_URL` com papel que ignora RLS (`BYPASSRLS` em produção) | Conferir `DATABASE_ADMIN_URL` no `.env`; nunca usar esse papel na API/worker. |
| `activate` recusado | Prontidão incompleta (configuração, documentos, conexão ou teste pendente) | `tenants readiness <slug>` lista cada pendência; resolver uma a uma e repetir. |
| `purge` recusado | Drenagem (`PURGE_DRENAGEM_SEGUNDOS`) não cumprida ou confirmação não bate com o nome exato | Esperar o tempo de drenagem; copiar o `nome_empresa` exatamente como cadastrado. |
| `ingest_docs` falha com `arquivo_grande`/`nao_suportado`/`sem_texto` | Arquivo > 5 MB, formato fora de `.md/.txt/.pdf`, ou PDF sem texto extraível | Reduzir/reformatar o arquivo antes de ingerir. |
| Resposta genérica ou handoff constante | `confianca_minima_handoff`/`min_similarity` muito altos para a base atual, ou base de conhecimento vazia/pequena | Revisar `tenant_config` (`config show`/`config set`) e confirmar `ingest_docs list` mostra trechos indexados. |
| Testes de integração falham ao rodar localmente | Postgres/Redis fora do ar | `docker compose up -d` antes de `make test-integration`. |

## 13. Referências

- [README.md](../README.md) — visão geral, stack, diagramas completos de arquitetura.
- [RUNBOOK_INCIDENTE.md](RUNBOOK_INCIDENTE.md) — pausar/investigar/retomar uma empresa em produção.
- [specs/001-router-support-agent/quickstart.md](../specs/001-router-support-agent/quickstart.md) — fluxo original de roteador e suporte.
- [specs/002-multitenancy/quickstart.md](../specs/002-multitenancy/quickstart.md) — passo a passo completo de multi-tenancy.
- [specs/002-multitenancy/contracts/tenants-cli.md](../specs/002-multitenancy/contracts/tenants-cli.md) — contrato completo da CLI do operador.
- [specs/002-multitenancy/contracts/onboarding-file.md](../specs/002-multitenancy/contracts/onboarding-file.md) — esquema do arquivo de onboarding.
- [docs/adr/](adr/) — decisões de arquitetura (orquestrador em `agents`, fila `arq`, resolução por conexão, exclusão de dados).
