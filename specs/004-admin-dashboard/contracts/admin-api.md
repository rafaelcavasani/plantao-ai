# Contrato: API de operação (`/admin/*`)

Fronteira entre o painel e o sistema (ADR-0005). Toda entrada e saída é validada com pydantic. Tudo em JSON UTF-8, exceto
o envio de documentos (`multipart/form-data`) e a exportação (`text/csv`). Datas em ISO 8601 UTC; o front formata em
`America/Sao_Paulo`. Valores monetários em US$ (número, 2 casas na exibição).

## Convenções

**Autenticação**: cookie de sessão `plantao_painel` (`HttpOnly; Secure; SameSite=Lax`). Sem sessão válida: **401**
`{"codigo":"nao_autenticado"}` em toda rota, exceto `/admin/auth/*` e `/painel/*` (arquivos estáticos).

**Papéis**: `leitura` pode todas as rotas `GET`; `operacao` pode também as rotas de escrita. Escrita com papel `leitura`:
**403** `{"codigo":"sem_permissao"}` (mesmo por chamada direta, FR-002).

**Requisições que alteram estado**: exigem `Origin` igual ao host do painel (senão **403** `origem_invalida`) e limite de taxa
por operador (**429** `limite_excedido`, com `Retry-After`).

**Erro padrão**:

```json
{ "codigo": "validacao", "mensagem": "Corrija os campos indicados.", "campos": { "slug": "Já existe uma empresa com o slug 'x'." } }
```

| HTTP | `codigo` | Quando |
|---|---|---|
| 400 | `validacao` | corpo inválido; `campos` traz mensagem por campo, em português |
| 401 | `nao_autenticado` | sem sessão, sessão expirada ou revogada |
| 403 | `sem_permissao`, `origem_invalida` | papel insuficiente; `Origin` inesperado |
| 404 | `empresa_nao_encontrada` | `slug` inexistente |
| 409 | `conflito_versao` | a empresa mudou desde que o formulário foi aberto; traz `atual` |
| 409 | `transicao_invalida` | mudança de estado fora da tabela do ciclo de vida; traz `estado_atual` e `permitidos` |
| 409 | `empresa_encerrada` | edição de empresa encerrada (FR-039) |
| 409 | `slug_em_uso`, `instancia_em_uso` | duplicidade (`ConexaoEmUso` do serviço) |
| 409 | `prontidao_reprovada` | ativação com itens pendentes; traz `itens` |
| 413 | `arquivo_grande` | arquivo acima de 2 MB |
| 404 | `conversa_nao_encontrada`, `remessa_nao_encontrada` | conversa de outra empresa ou inexistente; remessa expirada |
| 409 | `exclusao_recusada` | apagar dados fora das condições (empresa não encerrada, drenagem, nome errado) |
| 403 | `operador_nao_autorizado` | e-mail fora de `OPERADORES` no retorno do login |
| 415 | `formato_nao_suportado` | extensão fora da lista |
| 429 | `limite_excedido` | taxa por operador |
| 503 | `dados_desatualizados` | só em `/admin/saude`; ver abaixo |

Nenhuma resposta, em nenhum caso, contém: texto de mensagem, contato, segredo de entrega, chave de envio, hash de credencial
ou `Cookie`. Erros de validação nunca repetem o valor de campo secreto.

## Autenticação e sessão

| Método e rota | Papel | Descrição |
|---|---|---|
| `GET /admin/auth/entrar` | — | redireciona ao provedor OIDC (código + PKCE, `state`, `nonce`). Em `PAINEL_AUTH_MODE=dev`, entra com o operador fixo |
| `GET /admin/auth/retorno` | — | valida `state`, troca o código, valida o `id_token`; se o e-mail está em `OPERADORES`, cria a sessão e redireciona para `/painel/`; senão **403** `operador_nao_autorizado` |
| `POST /admin/auth/sair` | qualquer | apaga a sessão no Redis e o cookie |
| `GET /admin/eu` | qualquer | `{ "email": "...", "papel": "operacao", "expira_em": "..." }` |

## Leitura

Todos os blocos trazem `atualizado_em` (FR-027). Parâmetro `periodo`: `hoje`, `7d` ou `30d` (padrão `30d`).

### `GET /admin/visao-geral?periodo=`

```json
{
  "periodo": "30d", "fuso": "America/Sao_Paulo", "atualizado_em": "2026-10-06T14:02:00Z", "desatualizado": false,
  "empresas_por_estado": { "ativo": 9, "em_configuracao": 3, "suspenso": 2, "encerrado": 1, "total": 15 },
  "totais": {
    "mensagens": { "valor": 55530, "anterior": 48320, "recebidas": 29110, "agente": 26420, "humano": 0 },
    "conversas": { "valor": 9360, "anterior": 8305, "abertas": 214, "handoff": 7 },
    "taxa_handoff_pct": { "valor": 11.8, "anterior": 13.2 },
    "custo_usd": { "valor": 612.40, "anterior": 557.80 },
    "margem_usd": { "valor": 4120.10, "disponivel": true }
  },
  "serie": [ { "inicio": "2026-09-10T03:00:00Z", "recebidas": 2450, "agente": 2210, "humano": 0, "handoffs": 12, "conversas": 80, "tokens": 91000, "custo_usd": 61.2 } ],
  "funil": { "conversas": 4100, "respondidas_agente": 3600, "handoff": 540, "resolvidas_humano": 468 },
  "atencao": [ { "slug": "studio-fit", "nome": "Studio Fit Academia", "motivos": ["handoff_alto"], "gravidade": "aviso", "detalhe": "taxa de handoff 37,6% (limite 30%)" } ]
}
```

`anterior` é o período de mesma duração imediatamente anterior (FR-009). `atencao` usa os limites `PAINEL_LIMITE_*`
(FR-011, FR-012); `motivos` ∈ `sem_atividade`, `handoff_alto`, `custo_alto`, `conexao_nao_verificada`, `falhas_envio`; `gravidade` ∈ `critica`, `aviso`. O alerta de handoff só vale com pelo menos 5 conversas no período. Em `empresas[].atencao` cada item é `{codigo, gravidade, detalhe}`.
`margem_usd.disponivel = false` (e `valor = null`) quando algum plano em uso não tem preço. `orcamento_pct` usa o custo dos últimos 30 dias (janela móvel) sobre o orçamento mensal do plano, qualquer que seja o `periodo` escolhido.

### `GET /admin/empresas`

Parâmetros: `q` (nome ou slug), `estado`, `nicho`, `periodo`, `ordem` ∈ `nome, estado, mensagens, abertas, handoffs,
ultima_mensagem, custo, orcamento, criada_em`, `sentido` ∈ `asc, desc`, `pagina` (1), `tamanho` (≤ 100, padrão 25).

```json
{
  "total": 15, "pagina": 1, "tamanho": 25, "atualizado_em": "...",
  "itens": [ {
    "slug": "sorriso-vivo", "nome": "Clínica Sorriso Vivo", "nicho": "Clínica odontológica", "plano": "recepcionista",
    "estado": "ativo", "criada_em": "2026-08-12T...", "ativada_em": "2026-08-19T...",
    "mensagens": 4820, "conversas_abertas": 31, "handoffs": 62,
    "ultima_mensagem": { "em": "2026-10-06T13:59:00Z", "remetente": "lead" },
    "custo_usd": 74.20, "orcamento_usd": 100.0, "orcamento_pct": 74,
    "conexao": "verificada", "documentos": 6, "atencao": []
  } ]
}
```

`conexao` ∈ `verificada`, `nao_verificada`, `sem_conexao`. `ultima_mensagem` é `null` se a empresa nunca recebeu mensagem
(a tela mostra "sem mensagens"). `orcamento_usd` e `orcamento_pct` são `null` sem orçamento no plano.

### `GET /admin/empresas.csv`

Mesmos filtros de `/admin/empresas`, sem paginação. Colunas fixas: `slug, nome, nicho, plano, estado, criada_em, mensagens,
conversas_abertas, handoffs, minutos_desde_ultima_mensagem, custo_usd`. Sem dado pessoal (FR-015).

### `GET /admin/empresas/{slug}?periodo=`

Ficha. Reúne o que `tenants status` mostra (FR-016) e o atendimento do período (FR-017, FR-018).

```json
{
  "empresa": { "slug": "...", "nome": "...", "nicho": "...", "plano": "...", "estado": "ativo", "versao": 7,
               "criada_em": "...", "ativada_em": "...", "encerrada_em": null, "dados_apagados_em": null },
  "acoes_permitidas": [ { "para": "suspenso", "rotulo": "Suspender" }, { "para": "encerrado", "rotulo": "Encerrar" } ],
  "conexao": { "canal": "whatsapp", "provedor": "evolution", "instancia": "sorriso-vivo-wa", "verificada_em": "...", "credenciais": "configuradas" },
  "base": { "documentos": 6, "trechos": 148 },
  "prontidao": { "aprovada": true, "executada_em": "...", "operador": "...", "itens": [ { "id": "documentos", "ok": true, "rotulo": "Documentos da base de conhecimento enviados" } ] },
  "ultimo_teste": { "aprovado": true, "executado_em": "...", "operador": "..." },
  "atendimento": {
    "mensagens": { "lead": 0, "agente": 0, "humano": 0, "nao_texto": 0 },
    "conversas": { "abertas": 0, "handoff": 0, "resolvidas": 0, "por_canal": { "whatsapp": 0 } },
    "taxa_handoff_pct": 10.1, "motivos_handoff": [ { "motivo": "...", "total": 0 } ],
    "resposta_media_s": 4.2, "resposta_p95_s": 13, "intencoes": { "agendar": 0 },
    "bloqueios_guardrail": 0, "falhas_envio": 0
  },
  "custo": {
    "total_usd": 74.20, "tokens_entrada": 0, "tokens_saida": 0, "por_finalidade": { "roteador": 0, "suporte": 0, "embedding": 0 },
    "por_modelo": { "anthropic/claude-3-haiku": 0 }, "por_conversa_usd": 0.12,
    "orcamento_usd": 100.0, "orcamento_pct": 74, "preco_plano_usd": 450.0, "margem_usd": 375.80
  },
  "atencao": [], "atualizado_em": "..."
}
```

Empresa com `dados_apagados_em` preenchido: `atendimento`, `custo` e `base` vêm `null` e a tela mostra "dados apagados em <data>"
(US2, cenário 5). `margem_usd` é `null` quando o plano não tem preço (a tela mostra "margem indisponível", nunca zero).

### `GET /admin/empresas/{slug}/serie?periodo=`

Série para os gráficos: pontos de `inicio` com `recebidas`, `agente`, `humano`, `handoffs`, `custo_usd`, `tokens`. Granularidade:
hora (3 h na tela) para `hoje`, dia para `7d`, 3 dias para `30d`.

### `GET /admin/empresas/{slug}/configuracao`

Valores atuais de `tenant_config` (os mesmos campos do formulário) mais `versao`. Sem credenciais.

### `GET /admin/empresas/{slug}/auditoria?pagina=&tamanho=`

`audit_log` da empresa, mais recente primeiro: `{ criado_em, entidade, campo, valor_anterior, valor_novo, operador }`.
Credenciais aparecem como `"<atualizada>"` (marca do serviço), nunca como valor.

### `GET /admin/empresas/{slug}/conversas?pagina=`  e  `GET /admin/empresas/{slug}/conversas/{id}`

Somente metadados (US5, FR-005). Lista: `{ id_curto, id, canal, status, agente_atual, iniciada_em, ultima_atividade_em,
total_mensagens }`. Detalhe: os mesmos campos mais `handoff` (`motivo`, `confianca`, `em`) e a linha do tempo `{ remetente,
tipo, em, intencao, intencao_confianca, status_envio }`. Não existe campo de texto nem de contato; o contrato proíbe
acrescentá-los.

### `GET /admin/planos`

`[ { "chave": "recepcionista", "nome": "Recepcionista", "orcamento_mensal_usd": 100.0, "preco_mensal_usd": 450.0 } ]`, só leitura
(R-10), usado pelo formulário e pelas telas.

### `GET /admin/saude`

`{ "atualizado_em": "...", "idade_s": 95, "desatualizado": false }`. A tela usa para o aviso de dados desatualizados
(> 10 min, FR-027 e caso de borda de frescor). Responde **503** `dados_desatualizados` com o mesmo corpo quando passar de 10 min,
para monitoramento externo.

## Escrita (papel `operacao`)

Todas gravam auditoria com `operador = e-mail da sessão`, incrementam `tenants.versao` e respondem com a ficha atualizada
(mesmo corpo de `GET /admin/empresas/{slug}`), salvo indicação.

### `POST /admin/empresas`  (criar, FR-034)

```json
{
  "nome": "Clínica Exemplo", "slug": "clinica-exemplo", "nicho": "Clínica odontológica", "plano": "recepcionista",
  "configuracao": { "tom_de_voz": "...", "horario_funcionamento": { "seg": "08:00-18:00", "dom": "fechado" },
                     "limite_desconto_percentual": 10, "confianca_minima_handoff": 0.7,
                     "topicos_proibidos": ["..."], "palavras_gatilho": ["procon"],
                     "limite_mensagens_por_minuto": 20, "handoff_ttl_minutos": 120 },
  "conexao": { "instancia": "clinica-exemplo-wa", "segredo_entrega": "<≥32 caracteres>", "chave_envio": "<texto>" }
}
```

`conexao` é opcional na criação (a empresa nasce `em_configuracao` e a conexão pode vir depois). Regras (FR-035), validadas
no servidor com as mesmas funções do CLI: `slug` único, `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 63; instância não usada por outra empresa;
segredo ≥ 32 caracteres; chave não vazia; horário `HH:MM-HH:MM` ou `fechado` (dia `fechado` fica sem chave em `horario_funcionamento`); números nas faixas de `ConfigEmpresa` (desconto 0 a 100, confiança 0 a 1, mensagens por minuto 1 a 6000, duração do handoff 1 a 1440). `slug` com 3 a 63 caracteres. Os erros de configuração vêm como `campos["configuracao.<campo>"]`, os de conexão como `campos["conexao.<campo>"]`. **201**
com a ficha. Erros: 400 `validacao`, 409 `slug_em_uso` ou `instancia_em_uso`. Idempotência (FR-034): repetir o mesmo corpo (mesmo `slug` **e mesmo nome**) em uma empresa ainda `em_configuracao` completa o que falta, como `tenants create`. Slug de empresa em outro estado, ou com nome diferente, devolve 409 `slug_em_uso`. A empresa nova nasce na `versao` 1; só a alteração de uma existente incrementa.

`segredo_entrega` e `chave_envio` entram só por aqui e por `PUT .../conexao`; nunca saem em nenhuma resposta.

### `PATCH /admin/empresas/{slug}`  (editar, FR-036 a FR-039)

Corpo: `{ "versao": 7, "nome"?, "nicho"?, "plano"?, "configuracao"?: {campos alterados} }`. `slug` não pode mudar (400 se enviado
diferente). Só os campos que realmente mudam geram linha de auditoria, com valor anterior e novo (FR-037). Empresa encerrada:
**409** `empresa_encerrada` (FR-039). Empresa suspensa é editável. `versao` desatualizada:
**409** `conflito_versao` com `atual` (configuração e `versao` correntes) para a tela mostrar o conflito (FR-040). A resposta é a ficha com o campo extra `alteracoes` (quantos campos mudaram). Sem alterações: **200** com `alteracoes = 0`, sem tocar na versão nem na auditoria.

### `PUT /admin/empresas/{slug}/conexao`  (substituir credenciais, FR-038)

`{ "versao": 7, "instancia", "segredo_entrega", "chave_envio" }`. Chama `cadastrar_conexao`; troca de credencial zera
`channel_connections.verificada_em` (exige nova verificação) e audita com a marca `<atualizada>`.

### `POST /admin/empresas/{slug}/estado`  (FR-021, FR-022)

`{ "versao": 7, "para": "suspenso" | "ativo" | "encerrado", "motivo"?: "...", "confirmacao"?: "<nome exato>" }`.
- `encerrado` exige `confirmacao` igual ao nome da empresa (FR-007), senão 400 `validacao`.
- `ativo` a partir de `em_configuracao` exige prontidão aprovada (`ativar`); reprovada: 409 `prontidao_reprovada` com `itens`.
- Fora da tabela: 409 `transicao_invalida`.

### `POST /admin/empresas/{slug}/prontidao`  (FR-023)

Dispara `avaliar_prontidao` e devolve `{ "aprovada": false, "itens": [...] }`. A conversa de teste continua sendo disparada
pelo mesmo serviço do CLI, com o arquivo de teste da empresa, quando existir.

### `POST /admin/empresas/{slug}/documentos`  (JSON, FR-041)

Corpo `{ "arquivos": [ { "nome": "faq.md", "conteudo_base64": "..." } ] }`: até 10 arquivos, ≤ 2 MB cada (decodificados), extensões `.md`, `.txt` ou `.pdf` (as do ingestor); nomes repetidos na remessa são recusados com 400, formato inválido com 415 e arquivo grande com 413. Os bytes seguem em base64 dentro do JSON (sem `multipart`, para não acrescentar a dependência `python-multipart`). **202**
`{ "remessa": "<id>" }`.
`GET /admin/empresas/{slug}/documentos/remessas/{id}` → `{ "estado": "processando|concluida", "arquivos": [ { "nome", "status": "ok|inalterado|sem_texto|nao_suportado|arquivo_grande|falha", "trechos": 12 } ], "base": { "documentos": 7, "trechos": 160 } }`.

### `POST /admin/empresas/{slug}/apagar-dados`  (P3, FR-025)

Só para empresa `encerrada`. Primeiro `GET .../apagar-dados/resumo` (exige papel `operacao`) devolve o que será removido (contagens por tabela); depois
`POST` com `{ "confirmacao": "<nome exato>" }` chama `apagar_dados` e respeita a drenagem (`PURGE_DRENAGEM_SEGUNDOS`). Exige papel `operacao` e confirmação por nome.

### `POST /admin/atualizar`  (FR-042)

Enfileira `agregar_painel`. **202** `{ "enfileirado": true, "atualizado_em": "..." }`; no máximo uma por operador a cada 30 s
(429 depois).

## Arquivos estáticos

`GET /painel/*` serve `apps/dashboard/web/` sem autenticação (os arquivos não têm dado); qualquer chamada de dados exige a
sessão. `GET /painel/` redireciona para `#/` ou para o login conforme `GET /admin/eu`.

## Compatibilidade e testes de contrato

- Esquemas pydantic são a fonte; `tests/contract/test_admin_api.py` valida status, formato e, para cada rota, que **nenhuma**
  chave da resposta é `conteudo`, `contato*`, `segredo*`, `chave*`, `hash*` ou `external_id`.
- Teste negativo por papel: toda rota de escrita com papel `leitura` devolve 403 e não altera o banco.
- Mudança incompatível neste contrato exige atualizar esta spec antes (constituição VI).
