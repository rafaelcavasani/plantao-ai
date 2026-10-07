# Research: Painel de operação de empresas

Decisões tomadas na Fase 0 do plano. Cada uma segue o formato Decisão, Justificativa, Alternativas. As referências
`FR-` e `SC-` apontam para [spec.md](spec.md).

## R-01: Front-end sem framework e sem etapa de build

- **Decisão**: módulos ES nativos, HTML e CSS em `apps/dashboard/web/`, servidos como arquivos estáticos pela API em
  `/painel`. Roteamento por hash (`#/`, `#/empresas`, `#/empresa/<slug>`), como no protótipo.
- **Justificativa**: o protótipo `design-system/plantao-admin.html` já é JS puro e cobre as 4 telas. A equipe é de uma
  pessoa e o painel tem 4 telas e 1 a 5 usuários; um framework e uma cadeia de build adicionariam dependências sem
  retorno (princípio VIII). Sem build, o que se testa é o que se serve.
- **Alternativas**: React/Vite (mais ecossistema, mas build, `package.json`, auditoria de dependências npm e mais
  superfície de ataque), Streamlit/Retool (previstos no docstring antigo de `apps/dashboard`, mas fogem do design
  system e não dão o controle de privilégio e auditoria desejado).

## R-02: Gráficos em SVG próprio

- **Decisão**: linha, donut, funil e barras desenhados em SVG por `graficos.js`, com a matemática já validada no
  protótipo (donut por `stroke-dasharray` sobre uma circunferência; funil em escala relativa por etapa).
- **Justificativa**: 3 tipos de gráfico simples; evita biblioteca (R-01) e mantém o visual do design system.
- **Alternativas**: Chart.js e similares (peso e estilo próprio a sobrescrever).

## R-03: Agregação por job em tabelas dedicadas

- **Decisão**: `painel_agregado_hora` (uma linha por empresa e hora) e `painel_situacao` (uma linha por empresa, estado
  corrente) mantidas por um job ARQ. O job percorre as empresas e recalcula cada uma **dentro de `tenant_session`**, lendo
  `messages`, `conversations`, `handoff_log`, `llm_calls` e `knowledge_documents` sob RLS. Janela recalculada a cada
  execução: as últimas 3 horas e a hora corrente; uma execução diária refaz os 2 últimos dias (correções tardias).
- **Justificativa**: cumpre FR-042 (≤ 5 min) e SC-002 (3 s com 1 milhão de mensagens) lendo só tabelas pequenas
  (50 empresas × 24 h × 365 dias ≈ 440 mil linhas por ano). Como roda sob RLS por empresa, o princípio III vale também no
  cálculo.
- **Alternativas**: (a) visões materializadas: o `FORCE ROW LEVEL SECURITY` das tabelas de negócio faz o dono também ser
  filtrado, então a visão só enxergaria zero linhas sem uma política de exceção para o dono do banco; (b) consulta direta
  a cada abertura: lenta com histórico grande e disputa o banco do atendimento; (c) preencher `usage_metrics`: a tabela
  existe, mas nenhum código a escreve hoje (só `llm_calls` registra custo), e seus campos (diários, sem hora) não cobrem o
  período "Hoje".
- **Registro**: [ADR-0008](../../docs/adr/0008-agregacao-do-painel.md) (proposta).

## R-04: Papel `plantao_painel` com privilégio por coluna

- **Decisão**: o painel lê com o papel `plantao_painel` (`NOSUPERUSER NOBYPASSRLS`, só `SELECT`). O que ele pode ler
  vem de `GRANT SELECT (colunas)`: em `messages` só `id, tenant_id, conversation_id, remetente, tipo, intencao,
  intencao_confianca, status_envio, timestamp`; em `conversations` só as colunas sem `contato_hash` e `contato_enc`; sem
  nenhum privilégio em `channel_credentials`. Cada tabela lida ganha uma política `FOR SELECT TO plantao_painel USING
  (true)`, porque o RLS está forçado.
- **Justificativa**: transforma FR-004 e FR-005 numa propriedade do banco, não da disciplina do código: uma consulta
  errada na API falha com "permission denied" em vez de vazar texto. Teste de introspecção (`has_column_privilege`)
  prova isso.
- **Alternativas**: papel `plantao_app` com cuidado no código (descartado: acesso total a `conteudo`); papel
  administrativo (descartado em ADR-0006).

## R-05: Concorrência otimista por `tenants.versao`

- **Decisão**: coluna `versao int not null default 1`, incrementada por toda alteração feita por serviço do painel.
  `PATCH` e `POST .../estado` exigem a `versao` que o formulário leu; se diferir, a API devolve **409** com os valores
  atuais e o front mostra o conflito (FR-040).
- **Justificativa**: simples, sem trava longa; `mudar_estado` já usa `SELECT ... FOR UPDATE` e trava advisory, então o
  incremento fica na mesma transação.
- **Alternativas**: `ETag` a partir do último `audit_log` (frágil: alteração sem auditoria não muda a marca); trava
  pessimista de edição (ruim para sessões abandonadas).

## R-06: Autenticação OIDC com sessão no Redis

- **Decisão**: fluxo de código de autorização com PKCE e `state`/`nonce` (guardados no Redis por 10 min). A API troca o
  código por tokens com `httpx` e valida o `id_token` (assinatura, `iss`, `aud`, `exp`, `nonce`, e-mail verificado) com
  `PyJWT[crypto]` e as chaves públicas do provedor (JWKS, em cache curto). O e-mail precisa estar em `OPERADORES`
  (`email:papel,email:papel`, papel `leitura` ou `operacao`). Sessão: token aleatório de 256 bits, cookie `HttpOnly;
  Secure; SameSite=Lax`, valor em `painel:sessao:{hash}` no Redis com expiração deslizante de 30 min por inatividade e
  limite absoluto de 12 h (FR-006).
- **Justificativa**: ADR-0007. Sem senha para guardar, sem tabela de operadores (1 a 5 pessoas; mudar a lista é uma
  alteração de configuração no deploy). Sessão no servidor permite encerrar a sessão de verdade (logout, revogação).
- **Modo de desenvolvimento**: `PAINEL_AUTH_MODE=dev` entra com um operador fixo, e a aplicação **recusa subir** com
  esse modo se `ENV != development`. Testes usam `dependency_overrides`.
- **Alternativas**: biblioteca OIDC completa (Authlib: mais superfície que o necessário para um único provedor);
  `itsdangerous` com cookie assinado (sem revogação no servidor).

## R-07: Proteção contra requisições forjadas e cabeçalhos

- **Decisão**: toda rota que altera estado exige `Origin` igual ao host do painel e `Content-Type: application/json`
  (ou `multipart` no envio de documentos); CORS desabilitado. Respostas de `/painel` levam `Content-Security-Policy:
  default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:`, `X-Content-Type-Options:
  nosniff`, `Referrer-Policy: no-referrer` e `Frame-Options: DENY`. Limite de taxa por operador nas rotas de escrita
  (padrão 60 por minuto), com o mesmo mecanismo Redis de `apps/api/ratelimit.py`.
- **Justificativa**: `SameSite=Lax` sozinho não protege contra requisições de subdomínios irmãos; a checagem de `Origin`
  fecha a brecha sem token CSRF extra. CSP estrita só é possível sem script e estilo inline, o que o front real
  respeita (o protótipo é um arquivo único e inline, de propósito).

## R-08: Escrita com os serviços existentes e sessão administrativa isolada

- **Decisão**: `apps/api/admin/escrita.py` é o único módulo de `apps/` autorizado a importar `db.admin` (contrato
  `forbidden` do import-linter com exceção só para ele). Ele chama `criar_ou_continuar`, `aplicar_alteracoes`,
  `cadastrar_conexao`, `mudar_estado`/`suspender`/`retomar`/`encerrar`, `avaliar_prontidao`/`ativar` e `apagar_dados`,
  sempre com `operador = e-mail da sessão`. Cada rota abre **uma** transação, incrementa `tenants.versao` e confirma.
- **Justificativa**: paridade com a linha de comando é o critério de aceite do cadastro (SC-009); reaproveitar evita
  segunda implementação das mesmas regras. Escrita em `tenants` exige o papel dono (`plantao_app` só tem `SELECT` ali,
  migração 0003), então a sessão administrativa é inevitável; isolá-la num módulo limita o raio de dano.
- **Alternativas**: dar `UPDATE` em `tenants` ao `plantao_app` (afrouxa o isolamento do atendimento); chamar o CLI por
  subprocesso (frágil, sem tipagem, sem erros estruturados).

## R-09: Envio de documentos como job

- **Decisão**: `POST /admin/empresas/{slug}/documentos` (multipart) valida extensão (`.md`, `.txt`, vindas de
  `EXTENSOES_SUPORTADAS`), tamanho (≤ 2 MB por arquivo, ≤ 10 por remessa) e nomes repetidos, guarda os bytes no Redis por
  1 h e enfileira `ingerir_remessa`. O job chama `core.rag.ingest.ingerir_documento` por arquivo e grava o resultado
  (`ok`, `inalterado`, `sem_texto`, `arquivo_grande`, `falha`, com trechos) em `painel:remessa:{id}`. A tela consulta
  `GET .../documentos/remessas/{id}` até terminar e mostra o resultado (FR-041).
- **Justificativa**: ingerir chama o LLM de embeddings por lote; fazer isso na requisição HTTP bloquearia a API (e
  repetiria o erro que a constituição proíbe nos webhooks).
- **Alternativas**: síncrono na requisição (timeout em arquivos grandes); gravar arquivo em disco (estado fora do
  Redis/Postgres sem necessidade).

## R-10: Planos em arquivo versionado

- **Decisão**: `db/config_planos.py` define, para cada plano (`recepcionista`, `recepcionista_agendador`,
  `pacote_completo`), `orcamento_mensal_usd` e `preco_mensal_usd`, ambos opcionais. Plano sem valor mostra "sem
  orçamento" e "margem indisponível" (FR-043, FR-044). Leitura via `core/painel/planos.py`.
- **Justificativa**: segue o padrão de `db/config_padrao.py`; 3 planos não pedem tabela nem tela de edição. A "alteração
  auditada" do FR-044 é atendida pelo histórico do git do arquivo e pela revisão do PR.
- **Interpretação a confirmar**: se a intenção do FR-044 era trilha de auditoria *dentro* do painel, a evolução é uma
  tabela `planos` com linha de auditoria global (hoje `audit_log.tenant_id` é obrigatório). Não bloqueia esta versão.

## R-11: Frescor e botão "Atualizar"

- **Decisão**: cron ARQ `agregar_painel` a cada 2 minutos (folga para o limite de 5). `POST /admin/atualizar` enfileira o
  mesmo job (trava `painel:atualizar:lock` de 20 s, no máximo uma por operador a cada 30 s) e devolve o `atualizado_em`
  corrente; a tela consulta até o valor mudar. Cada resposta traz `atualizado_em` por bloco (FR-027); mais de 10 minutos
  sem atualização vira aviso de dados desatualizados.

## R-12: Tempo de resposta e percentil 95 a partir de histograma

- **Decisão**: por hora, guardar `resp_n`, `resp_soma_ms` e um histograma em baldes fixos (≤1 s, 2, 3, 5, 8, 13, 21, 34,
  55, 89, >89 s) em `resp_hist`. A média sai de `soma/n`; o p95 é estimado somando os histogramas do período.
- **Justificativa**: percentil não se agrega a partir de percentis por hora; o histograma é pequeno e suficiente para um
  painel de operação. O "tempo de resposta" é o intervalo entre a mensagem do contato e a resposta do agente
  (`messages.responde_a`).

## R-13: Fuso horário

- **Decisão**: `hora` é `timestamptz` em UTC; "hoje" e os dias das séries são calculados em `America/Sao_Paulo` na
  consulta (`AT TIME ZONE`), como o horário de funcionamento das empresas. As telas informam o fuso.

## R-14: Lista paginada, ordenada e filtrada no servidor

- **Decisão**: `GET /admin/empresas` com `q`, `estado`, `nicho`, `ordem` (lista fechada de colunas), `sentido`, `pagina`,
  `tamanho` (≤ 100). Ordem só por colunas da whitelist, nunca por texto livre. Os totais de mensagens, handoffs e custo
  da linha vêm de `painel_agregado_hora` no período; a "atenção" é calculada na consulta por `core/painel/atencao.py`.
- **Exportação** (FR-015): `GET /admin/empresas.csv` com os mesmos filtros, colunas fixas sem dado pessoal.

## R-15: Origem de "bloqueio por guardrail" e de falhas

- **Decisão**: `bloqueios_guardrail` conta linhas de `handoff_log` cujo `motivo` não é `falha_canal` nem baixa confiança
  (os guardrails de `core/guardrails` registram o motivo da decisão; ver `apps/worker/jobs.py`). `falhas_envio` conta
  `messages.status_envio = 'falha'` do agente.
- **A confirmar na implementação**: a lista exata de motivos de guardrail (hoje `decisao.motivo or "desconhecido"`). Se não
  houver motivo estável, o painel mostra só "handoffs por motivo" e remove o indicador separado.

## R-16: Observabilidade

- **Decisão**: logs JSON com `operador` (e-mail), `rota`, `empresa` (`slug`), `correlation_id`; nunca corpo da requisição,
  credencial ou `Cookie`. Registrar duração do job de agregação e número de empresas processadas; alerta no runbook se o
  `atualizado_em` mais antigo passar de 10 minutos.

## R-17: Recursos visuais auto-hospedados

- **Decisão**: fontes (Inter, Outfit) e ícones (Font Awesome Free) servidos de `apps/dashboard/web/assets/`, sem CDN, para
  a CSP estrita (R-07) e para não depender de terceiros em produção.
- **Pendência**: a pasta `assets/` do design system original (fontes, `themes.js`, overview e components) não existe no
  repositório; os tokens usados no protótipo foram derivados do `design-system.html`. Trazer esses arquivos antes da
  implementação dos componentes. Conferir também a licença dos arquivos de fonte e ícones antes de versioná-los.

## R-18: Retenção das linhas agregadas

- **Decisão**: manter 400 dias de `painel_agregado_hora`; o job diário apaga o que passar disso. A retenção do
  `audit_log` e da exclusão de dados continua nas regras da spec 002 (a exclusão por `purge` remove também as linhas
  `painel_*` da empresa: acrescentar as duas tabelas à lista de `core/tenancy/exclusao.py`).

## Itens de clarificação

Nenhum `NEEDS CLARIFICATION` ficou aberto no plano. A interpretação do FR-044 (R-10) e a lista de motivos de guardrail
(R-15) são pontos de confirmação, não bloqueios.
