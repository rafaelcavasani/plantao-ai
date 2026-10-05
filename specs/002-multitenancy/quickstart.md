# Quickstart: validar o multi-tenancy ponta a ponta

Guia de validação da feature 002. Cada cenário aponta o requisito que prova. Contratos em [contracts/](contracts/),
entidades em [data-model.md](data-model.md). Este guia não contém código de implementação.

## Pré-requisitos

- Docker Desktop, Python 3.11 e o `.venv` com `make install` (agora inclui `pyyaml` de runtime).
- Chaves da plataforma no `.env`: `PII_ENCRYPTION_KEY`, `PII_HASH_KEY`, `OPENROUTER_API_KEY` (só para os
  cenários com LLM real). `PILOT_TENANT_ID` e `WHATSAPP_WEBHOOK_SECRET` **não existem mais**.
- Uma instância da Evolution API por empresa (para o cenário com número real), com o webhook apontando para
  `POST /webhooks/whatsapp` e o header `X-Webhook-Token` igual ao segredo da empresa.
- Variáveis de ambiente por empresa para as credenciais (nomes referenciados no arquivo de onboarding).
  Gere o segredo de entrega com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## 1. Infraestrutura e migração

```text
make up
make migrate          # aplica até 0004
make test-integration # esperado: verde (inclui migracao 0004 up/down)
```

Esperado: tabelas `channel_connections`, `channel_credentials`, `readiness_checks` e `audit_log` existem com RLS
forçado; `tenants.status` só aceita os quatro estados.

## 2. Continuidade da empresa piloto (FR-032, SC-007)

1. Antes do passo 1, anote contagens da piloto: conversas, documentos, trechos, configuração.
2. Rode `make migrate`. Conferir: mesmas contagens, `status = ativo`, `slug = clinica-sorriso-piloto`.
3. Exporte as variáveis da piloto e rode `make tenant-create FILE=docs/exemplos/piloto.yml OPERADOR=<nome>`.
4. Esperado: empresa existente reutilizada, conexão criada, documentos `INALTERADO`, estado continua `ativo`.
5. Envie uma mensagem de teste ao número da piloto: resposta correta, enviada pelo número dela.
6. Rode `make evals SUITE=todas TENANT=clinica-sorriso-piloto`: metas SC-001 a SC-010 da 001 continuam atendidas.

## 3. Criar uma empresa nova do zero (US2, SC-001)

1. Copie `docs/exemplos/empresa-modelo.yml`, preencha dados, regras e `teste_prontidao`; coloque os documentos em
   uma pasta; exporte as duas variáveis de credencial.
2. `make tenant-create FILE=... OPERADOR=<nome>`. Esperado: resumo por passo, estado `em_configuracao`, nenhuma
   credencial impressa.
3. Repita o comando. Esperado: nada duplicado, `INALTERADO` nos documentos, nenhuma linha nova em `audit_log`.
4. `make tenant-readiness TENANT=<slug> OPERADOR=<nome>`. Esperado: pendência em "conversa de teste".
5. `python -m scripts.tenants test <slug> --operador <nome>` e `readiness` de novo: tudo OK.
6. `make tenant-activate ...`. Esperado: estado `ativo`, `ativado_em` preenchido, auditoria com operador.
7. Envie uma mensagem do celular ao número da empresa nova: resposta com os documentos dela.
8. **Medição de SC-001**: anote em uma tabela, para 2 criações seguidas, o tempo manual de cada etapa (preencher
   arquivo, gerar segredos, configurar instância e webhook na Evolution, rodar comandos, validar). Meta: até 2 h.

| Criação | Arquivo e documentos | Evolution e segredos | Comandos e validação | Total |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## 4. Recusas de ativação e de cadastro (US2 cenários 3 e 6, SC-010)

- Remova os documentos e rode `activate`: recusado, lista "documentos indexados".
- Arquivo com `confianca_minima_handoff: 1.5`: nada criado, erro no campo, saída 2.
- Segundo `create` com `instance_name` de outra empresa: recusado com mensagem clara.

## 5. Duas e três empresas ao mesmo tempo (US1, SC-002)

1. Tenha A, B e C ativas com documentos, horários, preços, limites de desconto e tópicos proibidos diferentes
   (os dados fictícios de B e C estão em `tests/evals/docs_empresa_b/` e `docs_empresa_c/`).
2. Pergunte "Qual o horário de sábado?" para o número de cada uma. Cada resposta vem dos documentos e do número
   da própria empresa.
3. `python -m scripts.run_evals --suite isolamento --tenants a,b,c` (LLM real, 30 perguntas por empresa).
   Esperado: 100% com resposta baseada na própria empresa e 0% com marcador de outra.
4. Mensagem para um número sem empresa: 401 no webhook, log `conexao_desconhecida`, nada gravado.

## 6. Suíte automática de isolamento (US3, SC-003, SC-009)

```text
python -m pytest -q tests/integration -k "isolamento"
```

Esperado (3 empresas): matriz por entidade, introspecção de RLS, quebra proposital detectada, e os cenários de
webhook e worker (mesmo telefone, mesmo `external_id`, credencial trocada, falha no canal de A, limite de A).
Confirme que o teste de quebra proposital **falha quando o isolamento é removido** (ele mesmo faz isso numa
transação revertida e espera a falha).

## 7. Suspensão, reativação e exclusão (US4, US6, SC-004, SC-008)

1. Com A e B ativas, `make tenant-suspend TENANT=a OPERADOR=<nome>`.
2. Envie mensagem para A: nenhuma resposta; histórico guardado com marca de suspensão. B responde normalmente.
3. `make tenant-resume ...`: novas mensagens de A voltam a ser respondidas; a mensagem da suspensão não é reprocessada.
4. `python -m scripts.tenants audit a`: duas linhas de estado (anterior, novo, operador, data).
5. Crie C com conversas, `close` C e rode `purge` sem `--confirmar`: nada apagado. Depois com o nome exato:
   contagens de C vão a zero, A e B idênticas, número liberado, auditoria da exclusão presente.

## 8. Configuração por empresa (US5, SC-005)

1. `config set a --operador <nome> limite_desconto_percentual=5`. A próxima mensagem de A usa 5%; B mantém o dela.
2. `config set a --operador <nome> min_similarity=2`: recusado, valor anterior preservado.
3. `audit a`: uma linha por campo com anterior, novo, operador e data.

## 9. Gates de qualidade (Definition of Done)

```text
make check   # ruff, mypy estrito, import-linter, pytest com cobertura, pip-audit
gitleaks detect
```

- `lint-imports`: contratos existentes continuam verdes; nenhum módulo de `apps/` importa `database_admin_url`.
- `.env.example`, `README.md` e `docs/RUNBOOK_INCIDENTE.md` atualizados; ADRs 0003 e 0004 presentes.
- Migração 0004: `alembic downgrade 0003` e `upgrade head` sem erro.

## Resultado esperado por critério

| Critério | Como validar |
|---|---|
| SC-001 | Seção 3, passo 8 (2 criações seguidas, até 2 h) |
| SC-002 | Seção 5, passo 3 |
| SC-003 | Seção 6 |
| SC-004 | Seção 7 passos 1 a 3 e teste automático com canal fake (latência de B e corte de A em até 1 min) |
| SC-005 | Seção 8 |
| SC-006 | Teste de integração com limite excedido em A e medição de B (>= 90% em até 10 s) |
| SC-007 | Seção 2 |
| SC-008 | Seção 7 passo 5 |
| SC-009 | Seção 6 (contrato do webhook: token de A com instância de B) |
| SC-010 | Seção 4 |
