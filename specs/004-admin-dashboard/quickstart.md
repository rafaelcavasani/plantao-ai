# Quickstart: validar o painel de ponta a ponta

Guia de validação. Os comandos `make painel-dev`, `make painel-seed` e `make test-web` já existem. Contratos em [contracts/](contracts/), modelo em [data-model.md](data-model.md).

## Pré-requisitos

- Docker Desktop com Postgres e Redis (`make up`), venv instalado (`make install`), migrações aplicadas (`make migrate`, inclui `0005_painel`).
- `.env` com as chaves de PII e, para o painel em desenvolvimento: `PAINEL_AUTH_MODE=dev`, `OPERADORES=voce@exemplo.com:operacao,leitor@exemplo.com:leitura`, `DATABASE_PAINEL_URL` e `PAINEL_DB_PASSWORD`.
- Empresas de teste com mensagens: `make painel-seed` cria 5 empresas fictícias (uma suspensa, uma em configuração) com 30 dias de histórico e roda a agregação. Para o cadastro, use também `docs/exemplos/empresa-modelo.yml` com `make tenant-create`.

## 1. Subir

```text
make painel-dev  # API em http://localhost:8000 com o login de desenvolvimento (só com ENV=development)
make worker       # worker, que roda o cron agregar_painel a cada 2 min
```

Abrir `http://localhost:8000/painel/`. Em modo `dev` o login entra direto como o primeiro operador de `OPERADORES`.

## 2. Cenários de aceite

| # | Cenário | Como validar | Esperado | Critério |
|---|---|---|---|---|
| 1 | Visão geral confere com a base | Abrir `#/`, trocar `Hoje`/`7d`/`30d`; comparar com `SELECT` direto em `messages`/`llm_calls` por empresa | Números idênticos aos da base para o período | SC-003, FR-028 |
| 2 | Frescor | Enviar uma mensagem de teste; esperar ≤ 5 min ou clicar `Atualizar` | "Última mensagem" e contadores refletem a nova mensagem | FR-042 |
| 3 | Atenção | Parar de enviar mensagens a uma empresa ativa (ou ajustar `PAINEL_LIMITE_SILENCIO_HORAS=0`) | Ela aparece em "Atenção ao vivo" e com ícone na tabela | FR-011, SC-007 |
| 4 | Ficha | Abrir `#/empresa/<slug>`; comparar com `make tenant-status SLUG=<slug>` | Mesmos dados de identificação, estado, conexão, documentos, prontidão | FR-016 |
| 5 | Sem dado pessoal | Chamar cada rota `/admin/*` com a sessão e procurar `conteudo`, `contato`, `segredo`, `chave`, `hash` | Nenhuma ocorrência; teste de contrato automatizado | SC-004, FR-004 |
| 6 | Privilégio de coluna | `psql` como `plantao_painel`: `SELECT conteudo FROM messages LIMIT 1;` | `permission denied for table messages` | FR-005, ADR-0006 |
| 7 | Suspender e retomar | Ficha → Suspender (com motivo) → conferir `make tenant-status` e `make tenant-list` → Retomar | Estado muda nas duas pontas; auditoria com o e-mail do operador; nova mensagem durante a suspensão não é respondida | SC-005, SC-006 |
| 8 | Encerrar exige nome | Ficha → Encerrar | Botão só habilita com o nome exato | FR-007 |
| 9 | Ativação bloqueada | Empresa em configuração sem documentos → Ativar | Janela lista os itens pendentes; nada muda | FR-022 |
| 10 | Papel de leitura | Entrar como `leitor@exemplo.com`; abrir `#/empresas/nova` e chamar `POST /admin/empresas` com `curl` | Tela de "sem permissão" e **403** na API; nada gravado | FR-002 |
| 11 | Cadastro equivale ao CLI | `#/empresas/nova` com o conteúdo de `docs/exemplos/empresa-modelo.yml`; depois `tenants create --file` com o mesmo arquivo em outro slug; comparar `tenants status` e `tenants audit` | Resultado equivalente (campos, estado `em_configuracao`, auditoria) | SC-009 |
| 12 | Validações | Tentar slug repetido, instância em uso, segredo curto, horário inválido | Erro junto ao campo; nada criado; nenhuma credencial em tela, rede ou log | SC-010, FR-035 |
| 13 | Credenciais não voltam | Editar empresa com conexão; inspecionar a aba de rede | Resposta só diz "configuradas"; nenhum valor | FR-038 |
| 14 | Edição simultânea | Abrir a mesma empresa em duas abas; salvar na primeira e depois na segunda | Segunda recebe o conflito com os valores atuais | FR-040 |
| 15 | Documentos | Enviar `.md` válido, `.txt` repetido e `.exe` | Remessa mostra `ok` / recusa nome repetido / recusa formato; contagem na ficha sobe | FR-041 |
| 16 | Sessão | Esperar `PAINEL_SESSAO_INATIVIDADE_MIN` (ou reduzir a 1) e agir | Volta ao login e retorna à tela de origem | FR-006 |
| 17 | Isolamento | `make test` (suíte de isolamento com duas empresas + painel) | Verde; a soma da visão geral é a soma das duas empresas | Constituição III |
| 18 | Desempenho | `pytest -m lento tests/integration/test_painel_desempenho.py` (50 empresas, ~1 milhão de mensagens) | ≤ 3 s por rota; medido: visão geral 0,29 s, ficha 0,17 s | SC-002 |
| 19 | Celular | Abrir `#/`, `#/empresas`, `#/empresa/<slug>` em 390 px | Sem rolagem horizontal da página; menu sobreposto | SC-008 |

## 3. Testes automatizados

```text
make test-unit                       # inclui tests/unit/painel
make test                            # inclui integração (Postgres/Redis) e contrato de /admin/*
make test-web                        # funções puras do front-end (node --test)
pytest -m lento tests/integration/test_painel_desempenho.py   # SC-002: 50 empresas e ~1 milhão de mensagens
make lint && make typecheck          # ruff, mypy e import-linter (contrato novo da sessão administrativa)
```

## 4. Operação (para o RUNBOOK)

- Adicionar ou remover operador: editar `OPERADORES` no ambiente e reiniciar a API.
- Painel "desatualizado": conferir se o worker está no ar (cron `agregar_painel`); `GET /admin/saude` mostra a idade dos dados.
- Alterar orçamento ou preço de plano: PR em `db/config_planos.py`.

## 5. O que cada cenário já tem de prova automatizada

| Cenários | Prova |
|---|---|
| 1, 2, 3, 4 | `tests/integration/test_painel_visao_geral.py`, `test_painel_ficha.py`, `test_painel_agregacao.py` |
| 5, 6 | `tests/contract/test_admin_leitura.py`, `tests/integration/test_painel_privilegios.py` |
| 7, 8, 9, 10 | `tests/integration/test_painel_estado.py` |
| 11, 12, 13, 14, 15 | `tests/integration/test_painel_cadastro.py` |
| 16 | `tests/unit/test_painel_auth.py`, `tests/contract/test_admin_seguranca.py` |
| 17 | `tests/integration/test_isolamento_*.py`, `test_painel_isolamento.py` |
| 18 | `tests/integration/test_painel_desempenho.py` (marcado `lento`) |
| 19 | Chrome real a 390 px: `scripts/painel_e2e/navegador-real.mjs` (ver `checklists/ui.md`) |

Além disso, dois scripts opcionais em `scripts/painel_e2e/` (dependências fora do projeto) repetem a verificação:
`fumaca-jsdom.mjs` carrega o front real contra a API real e exercita login, visão geral, empresas, ficha, suspensão e retomada,
encerramento com nome exato, cadastro com validação, edição, conversas e sessão inválida; `navegador-real.mjs` mede, em Chrome de
verdade, CSP, `axe-core` WCAG 2.1 AA, rolagem horizontal a 390/768/1000 px, colunas dos KPIs, menu do celular, foco preso na janela,
movimento reduzido e fontes.
