# Revisão de segurança do painel (T085)

**Feature**: [spec.md](../spec.md) | **Decisões**: [ADR-0006](../../../docs/adr/0006-leitura-entre-empresas-pela-api.md), [ADR-0007](../../../docs/adr/0007-autenticacao-do-operador.md), [research.md](../research.md) R-04 a R-08

Revisão feita sobre o código implementado (API `apps/api/admin`, `core/painel`, `db/`, front `apps/dashboard/web`). Cada
item cita o teste que o prova, quando existe.

## Achados corrigidos durante a revisão

| # | Achado | Gravidade | Correção | Prova |
|---|---|---|---|---|
| 1 | `GET /admin/empresas/{slug}/documentos/remessas/{id}` estava sem exigência de sessão: qualquer pessoa com o id (32 caracteres aleatórios) lia nomes de arquivo e status | média | a rota passou a exigir sessão (`OperadorAtual`) | `test_toda_rota_de_dados_exige_sessao` varre o OpenAPI e exige 401 em **toda** rota `/admin` fora do login |
| 2 | Corpo de arquivo em base64 sem limite de tamanho: um operador autenticado poderia enviar JSON gigante | baixa | `conteudo_base64` limitado a 2,9 milhões de caracteres (2 MB decodificados) e no máximo 10 arquivos | `test_remessa_recusa_nome_repetido_formato_e_tamanho` |
| 3 | Sem `Strict-Transport-Security` | baixa | cabeçalho enviado em `/painel` e `/admin` fora de desenvolvimento e teste | `test_hsts_so_fora_de_desenvolvimento` |
| 4 | Cliente HTTP do provedor OIDC nunca era fechado | baixa | `fechar_oidc()` no desligamento da API | revisão de código |
| 5 | Cores com `var(--...)` em atributos de apresentação SVG (sparkline) não são garantidas em todo navegador | baixa | cores concretas no sparkline | revisão de código |
| 6 | Login sem OIDC configurado devolvia 500 com stack trace | baixa | 503 `login_nao_configurado` e 502 `provedor_indisponivel`, sem detalhe interno | `test_login_sem_oidc_configurado_devolve_503_claro_e_nao_500` |

## Autenticação e sessão

- [x] Sem sessão, toda rota de dados responde 401 (`test_toda_rota_de_dados_exige_sessao`, `test_sem_sessao_devolve_401`)
- [x] Token de sessão de 256 bits, guardado no Redis só como `sha256`; novo token a cada login (sem fixação de sessão) (`test_sessao_guarda_so_o_hash_do_token`)
- [x] Expiração por inatividade (30 min, deslizante) e teto de 12 h; quem sai de `OPERADORES` perde a sessão (`test_painel_auth.py`)
- [x] `id_token`: assinatura RS256, `iss`, `aud`, `exp`, `nonce` e e-mail verificado; `alg=none` e chave desconhecida recusados (`test_painel_auth.py`)
- [x] `state` de uso único (`GETDEL`) e `nonce`; PKCE com `S256` (vetor da RFC 7636 testado)
- [x] Cookie `HttpOnly`, `SameSite=Lax`, `Secure` fora de desenvolvimento (`test_cookie_em_producao_e_secure`)
- [x] Login de desenvolvimento só com `ENV=development`; a API recusa subir com `PAINEL_AUTH_MODE=dev` fora disso (`test_modo_dev_fora_de_development_impede_a_subida`)
- [x] Redirecionamento após o login nunca sai do painel (`test_destino_de_login_nunca_sai_do_painel`)

## Autorização

- [x] Papel `leitura` só lê; toda rota de escrita exige `operacao` (403 mesmo por chamada direta) (`test_papel_de_leitura_nao_altera_nada`, `test_papel_de_leitura_nao_cria`)
- [x] Rotas de escrita exigem `Origin` igual ao host (`test_post_sem_origin_e_recusado`, `test_post_com_origin_de_outro_site_e_recusado`) e respeitam o limite de 60 por minuto por operador (`test_limite_de_taxa_por_operador`)
- [x] Só `apps/api/admin/escrita.py` importa `db.admin` (import-linter e `test_nenhum_arquivo_em_apps_importa_o_papel_administrativo`)
- [x] Slug, id de remessa e id de conversa validados por padrão antes de qualquer consulta (`test_slug_mal_formado_nunca_chega_ao_banco`)

## Dados e isolamento

- [x] O papel `plantao_painel` não lê `messages.conteudo`, `external_id`, `conversations.contato_*`, `tenant_knowledge`, credenciais nem `leads`, e não escreve em tabela alguma (`test_painel_privilegios.py`)
- [x] Consultas com `SELECT *` em tabelas de conteúdo falham no banco (`test_banco_recusa_ler_texto_e_contato_pelo_papel_do_painel`)
- [x] Tabelas novas com `tenant_id`, RLS forçado e teste de isolamento entre empresas (`test_painel_isolamento.py`, matriz de `test_isolamento_tenants.py`)
- [x] A agregação roda sob `tenant_session`, empresa por empresa (`test_painel_agregacao.py`)
- [x] Nenhuma resposta, log ou linha de auditoria contém segredo de entrega, chave de envio, texto de mensagem ou contato (`test_credenciais_nunca_aparecem_em_resposta_nem_em_log`, `chaves_proibidas` nos testes de contrato)
- [x] Todo SQL liga parâmetros; ordenação só por colunas de uma lista fixa (`test_parametros_de_lista_invalidos_devolvem_400`)
- [x] Exportação CSV sem dado pessoal e com neutralização de fórmulas de planilha (`test_exportacao_csv_tem_colunas_fixas_e_neutraliza_formula`)
- [x] `pip-audit`: nenhuma vulnerabilidade conhecida em `requirements.txt`
- [x] `gitleaks protect --staged` (imagem oficial, via docker) sobre os 128 arquivos do commit: nenhum vazamento; o `.env` não entra no commit

## Navegador

- [x] Em Chrome real: nenhuma violação de CSP nas 6 telas, console e rede limpos (`scripts/painel_e2e/navegador-real.mjs`)
- [x] CSP `default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:` sem `unsafe-inline` nem `unsafe-eval` (`test_arquivos_do_painel_levam_csp_estrita`); `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`
- [x] Front sem `innerHTML` e sem atributo `style` (`dom.js` lança erro); texto da API sempre como nó de texto
- [x] Nenhum segredo em `localStorage`, `sessionStorage` ou URL
- [x] Fontes e ícones servidos pela própria API, sem CDN

## Riscos residuais (aceitos ou pendentes)

- Leituras (`GET`) não têm limite de taxa; só escrita e "Atualizar". Aceitável para 1 a 5 operadores autenticados; revisar se o painel for exposto a mais gente.
- Não há proteção contra força bruta no login: ela fica com o provedor OIDC.
- O e-mail do operador aparece nos logs e na auditoria (necessário para a trilha); não é dado de cliente final.
