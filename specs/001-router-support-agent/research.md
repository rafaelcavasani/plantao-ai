# Research: Agente Roteador e Agente de Suporte

Todas as decisões abaixo resolvem pontos em aberto do Technical Context de [plan.md](plan.md). Nenhum item
`NEEDS CLARIFICATION` permanece. Valores numéricos são **iniciais** e devem ser calibrados com
`scripts/run_evals.py` (ver [quickstart.md](quickstart.md)).

## R-01. Gateway de LLM e embeddings

- **Decision**: cliente próprio com `httpx` falando o protocolo compatível com OpenAI do OpenRouter
  (`/chat/completions` e `/embeddings`), atrás do Protocol `LLMClient` em `core/llm/ports.py`.
  Embeddings: `openai/text-embedding-3-small` (1 536 dimensões, igual à coluna `Vector(1536)` atual).
- **Rationale**: constitution I exige LLM só via OpenRouter por camada única. `httpx` já é dependência, evita
  atrelar o domínio ao SDK do LangChain e facilita o fake em testes. O custo vem do campo `usage` da resposta.
- **Alternatives considered**: `langchain-openai` (já em `requirements.txt`; adiciona abstração sem ganho para
  duas chamadas simples); SDK da OpenAI direto (viola constitution I); modelo de embedding local (nova
  infraestrutura, sem ganho para 1 tenant).
- **Risco**: confirmar na conta OpenRouter que o endpoint de embeddings está habilitado. Mitigação: a porta
  `embed()` permite trocar o provedor sem tocar no restante.

## R-02. Fila e worker

- **Decision**: `arq` sobre Redis. O webhook persiste a mensagem e enfileira só o `message_id`; o job lê o
  restante do banco.
- **Rationale**: ARQ é async nativo, combina com SQLAlchemy async e FastAPI, tem retry e timeout por job.
  Enfileirar apenas o id mantém telefone e texto fora do Redis (princípio IV).
- **Alternatives considered**: RQ/Celery (citados na seção 8.2, mas síncronos; exigiriam ponte para código
  async); `BackgroundTasks` (perde jobs em reinício, sem retry); processar inline (viola FR-016).
- **Registro**: ADR-0002.

## R-03. Idempotência (FR-015, SC-008)

- **Decision**: chave única `(tenant_id, external_id)` em `messages`, com `INSERT ... ON CONFLICT DO NOTHING`.
  Se não inseriu, o webhook responde 200 e não enfileira. O job também verifica se já existe resposta do agente
  para o `message_id` antes de processar (cobre reenvio do próprio ARQ).
- **Rationale**: a garantia fica no banco, sobrevive a reinício e não depende de TTL de cache.
- **Alternatives considered**: `SET NX` no Redis com TTL (expira, perde garantia, estado duplicado).

## R-04. Conversa e handoff

- **Decision**: reaproveitar a conversa mais recente do mesmo contato (`tenant_id`, `canal`, `contato_hash`)
  com atividade nas últimas 24 h. Conversa em `handoff` não recebe resposta automática; as mensagens são
  gravadas. Após `HANDOFF_TTL_MINUTES = 60` sem atividade humana registrada, a próxima mensagem reabre a
  conversa para o automático.
- **Rationale**: evita o bug atual (uma conversa por mensagem), dá contexto para perguntas de seguimento
  (FR-010) e evita que o robô fale por cima de um atendente.
- **Alternatives considered**: sempre responder mesmo em handoff (conflita com a ideia de repasse); handoff
  permanente (cliente fica sem resposta sem painel de atendentes neste sprint).
- **Ponto em aberto**: se o TTL de 60 min é adequado depende do piloto. Reavaliar em `/speckit.clarify` ou
  no beta. Impacto de mudança é uma constante.

## R-05. Roteador

- **Decision**: LLM barato (`settings.model_cheap`) com saída JSON validada por pydantic:
  `{intencao, confianca, intencoes_secundarias[]}`. Limite `router_confidence_threshold = 0.6`; abaixo disso a
  intenção vira `suporte` (padrão seguro, FR-002). Entradas: mensagem + últimas 6 mensagens.
- **Rationale**: latência e custo baixos (seção 8.4). Validação com pydantic e 1 retry de parse; segunda falha
  vira handoff `falha_llm`.
- **Alternatives considered**: classificador por regras (frágil para linguagem natural); embeddings + k-NN
  (precisa de exemplos rotulados que ainda não existem); modelo forte (custo sem necessidade).
- **Intenção mista (edge case)**: a principal manda o fluxo; as secundárias só são gravadas em
  `messages.intencoes_secundarias`.

## R-06. Ingestão e chunking

- **Decision**: texto (`.txt`, `.md`) lido direto; PDF via `pypdf` (apenas texto, sem OCR). Chunking com
  `RecursiveCharacterTextSplitter` de `langchain-text-splitters`: 800 caracteres, overlap 100. Embeddings em
  lotes de 64. Recarga de documento: transação única que apaga os trechos antigos do mesmo
  `(tenant_id, nome_origem)` e insere os novos (FR-012).
- **Rationale**: simples, determinístico, testável sem rede. `pypdf` é puro Python. Splitter já está instalado
  como dependência transitiva de `langchain`.
- **Alternatives considered**: `unstructured` (pesado); OCR (fora de escopo, assumption da spec); chunking
  semântico (complexidade sem dado que justifique).
- **Limite conhecido**: PDFs escaneados retornam texto vazio. O CLI avisa e não indexa.

## R-07. Recuperação e confiança do suporte

- **Decision**: busca por similaridade de cosseno (índice HNSW), `top_k = 4`, filtrada por `tenant_id`.
  Descartar trechos com similaridade `< min_similarity = 0.30` (config por tenant). Sem nenhum trecho restante,
  handoff `sem_resposta_na_base` **sem chamar o LLM** (economiza custo e elimina alucinação).
  O LLM de suporte devolve `{responde, confianca, resposta, trechos_usados[]}`. Confiança final =
  `min(confianca_do_llm, f(similaridade_maxima))`, com `f` linear entre 0,30 (→ 0) e 0,60 (→ 1).
  `confianca_minima_handoff` do tenant (padrão 0,7) decide o envio.
- **Rationale**: duas fontes independentes de confiança reduzem falso positivo. O limiar inicial vem do
  `TenantConfig` já existente.
- **Calibração**: os limiares 0,30 / 0,60 são palpites para `text-embedding-3-small`. Devem ser ajustados com
  o dataset de avaliação (SC-001, SC-002, SC-009). Não alterar sem rodar `run_evals.py`.
- **Alternatives considered**: auto-avaliação apenas do LLM (viés de excesso de confiança); reranker (nova
  dependência sem evidência de necessidade).

## R-08. Criptografia e mascaramento de PII

- **Decision**: `conversations` guarda `contato_hash` (HMAC-SHA256 com `PII_HASH_KEY`, para busca) e
  `contato_enc` (Fernet com `PII_ENCRYPTION_KEY`, para enviar a resposta). Logs passam por um filtro que
  mascara telefones (`+55 11 9****-1234`). Conteúdo das mensagens não é criptografado por coluna: não é dado
  pessoal estruturado e precisa ser consultável; o acesso é protegido por RLS.
- **Rationale**: constitution IV exige criptografia em repouso para telefone e nome. HMAC permite lookup sem
  expor o número. `cryptography` é padrão de mercado.
- **Alternatives considered**: `pgcrypto` (chave trafega em SQL e fica em logs de query); armazenar em texto
  (viola IV).
- **Rotação de chaves**: fora de escopo. Registrar como dívida em ADR quando houver mais de um tenant.

## R-09. Row-Level Security e papel de banco

- **Decision**: migração 0003 cria o papel `plantao_app` (sem `SUPERUSER`, sem `BYPASSRLS`), habilita
  `ENABLE` + `FORCE ROW LEVEL SECURITY` em todas as tabelas com `tenant_id`, com política
  `tenant_id = current_setting('app.tenant_id')::uuid`. A aplicação conecta como `plantao_app`; migrações como
  o dono. O tenant vem de `SET LOCAL app.tenant_id` no início de cada transação (`tenant_session()`).
  O tenant piloto vem de `PILOT_TENANT_ID` (variável de ambiente), não de `SELECT ... LIMIT 1`.
- **Rationale**: o usuário atual do docker-compose é superusuário e ignora RLS. Sem papel dedicado o teste de
  isolamento passaria sem provar nada.
- **Alternatives considered**: filtrar só na aplicação (viola III); schema por tenant (complexidade
  desnecessária).

## R-10. Defesa em profundidade contra injeção e invenção

- **Decision**: (1) entrada determinística antes do LLM (gatilhos, vazio, não texto); (2) prompts com conteúdo
  não confiável entre delimitadores (`<mensagem_cliente>`, `<trecho id="...">`) e regra explícita de tratar
  como dado; (3) saída validada por schema; (4) **fundamentação**: todo valor monetário, percentual e número de
  horário citado na resposta deve existir literalmente nos trechos usados, senão handoff
  `valor_nao_fundamentado`; (5) tópicos proibidos e limite de desconto do tenant; (6) o LLM não tem ferramentas
  neste sprint (privilégio mínimo).
- **Rationale**: nenhuma camada sozinha é confiável. A checagem 4 é determinística e cobre o risco mais caro
  (preço inventado, FR-006).
- **Alternatives considered**: LLM juiz para validar a resposta (custo e latência extras); lista de
  bloqueio de frases de injeção (fácil de contornar).

## R-11. Saídas estruturadas e modelos

- **Decision**: pedir JSON no prompt e validar com pydantic; 1 retry em falha de parse; depois handoff.
  Roteador e suporte usam `settings.model_cheap` neste sprint. `model_strong` fica reservado para decisões
  críticas em sprints futuros.
- **Rationale**: independente do suporte a `json_schema` de cada modelo no OpenRouter.
- **Estimativa de custo (SC-006)**: roteador ≈ 600 tokens de entrada + 60 de saída; suporte ≈ 1 800 de entrada
  + 250 de saída; embedding da pergunta ≈ 30 tokens. Com preço de referência de US$ 0,25 / 1,25 por 1 M de
  tokens: ≈ US$ 0,0009 por conversa. Margem de ~10x sobre o teto de US$ 0,01.

## R-12. Resiliência

- **Decision**: timeout de 15 s por chamada de LLM, 1 retry com backoff de 1 s apenas em erro de rede ou 5xx.
  Qualquer falha final gera handoff `falha_llm` e linha em `llm_calls` com `sucesso = false`. Timeout de envio
  ao canal de 10 s; falha marca `status_envio = falha` e não derruba o job.
- **Rationale**: Restrições Adicionais da constituição (timeout, retry limitado, degradar para handoff).
- **Orçamento de latência (SC-004)**: embedding 0,3 s + busca 0,1 s + roteador 1 s + suporte 3 s +
  guardrails 0,05 s + envio 0,5 s ≈ 5 s típico, margem para o p90 de 10 s.

## R-13. Observabilidade

- **Decision**: log JSON com `correlation_id` (gerado no webhook, propagado ao job), `tenant_id`,
  `conversation_id`. Uma linha em `llm_calls` por chamada. Handoffs em `handoff_log`. LangSmith permanece
  opcional (Sprint 6).
- **Rationale**: FR-017, FR-018, FR-022 e princípio VII.

## R-14. Dependências e lockfile

- **Decision**: manter `requirements.txt` com faixas e gerar `requirements.lock` com `pip-compile` (pip-tools),
  usado pelo CI e pelo deploy. `pip-audit` roda sobre o lock.
- **Rationale**: constitution I exige versões fixadas e auditadas.
- **Alternatives considered**: Poetry/uv (mudança de ferramenta sem necessidade neste sprint).

## Itens fora de escopo confirmados

Agendador, SDR, cobrança, painel, LangSmith, orçamento por tenant, interpretação de áudio e imagem, painel de
atendentes, rotação de chaves de PII, multi-tenant real (resolução por número de destino).
