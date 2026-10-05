# Contrato: CLI do operador

Implementa FR-011 a FR-021, FR-029 e US2, US4, US5, US6. Arquivo: `scripts/tenants.py`. Execução:
`python -m scripts.tenants <comando> ...`. Usa `DATABASE_ADMIN_URL` para operações entre empresas
(research R-16) e `tenant_session` para dados de uma empresa. Não há empresa padrão: todo comando recebe o
`slug` (FR-021). Nenhuma saída contém credenciais, telefone ou texto de cliente final (FR-005).

**Convenções**

- `--operador NOME` é **obrigatório** em todo comando que altera algo; entra em `audit_log` (spec, Assumptions).
- Código de saída: `0` sucesso; `1` operação recusada (estado inválido, prontidão incompleta, confirmação
  errada) ou falha externa; `2` uso incorreto ou arquivo inválido.
- Mensagens e cabeçalhos em português, como a CLI de conhecimento da 001.

## Comandos

| Comando | Efeito | Requisitos |
|---|---|---|
| `create --file F --operador N` | onboarding repetível ([onboarding-file.md](onboarding-file.md)) | FR-012, FR-013 |
| `list` | `slug`, nome, estado, ativada em, conexão (instância, verificada em) de cada empresa | |
| `status SLUG` | estado, datas, configuração resumida, documentos, conexão, última prontidão e último teste | |
| `readiness SLUG --operador N` | avalia os 4 itens, grava `readiness_checks` e imprime item a item | FR-014 |
| `test SLUG --operador N` | executa a conversa simulada do arquivo e grava o resultado | FR-014, R-10 |
| `activate SLUG --operador N` | reavalia a prontidão; ativa se aprovada, recusa e lista pendências | FR-015, SC-010 |
| `suspend SLUG --operador N [--motivo T]` | `ativo -> suspenso` | FR-016 |
| `resume SLUG --operador N` | `suspenso -> ativo` | FR-018 |
| `close SLUG --operador N` | `-> encerrado`; número continua reservado | FR-019, FR-020 |
| `purge SLUG --operador N --confirmar "NOME"` | apaga os dados da empresa encerrada | FR-019, SC-008 |
| `config show SLUG` | configuração atual (valores, não segredos) | |
| `config set SLUG --operador N campo=valor ...` | altera campos validados; auditoria por campo | FR-009, FR-010, FR-029 |
| `audit SLUG [--limite N]` | últimas linhas de auditoria (campo, anterior, novo, operador, data) | FR-029 |

`valor` em `config set` é interpretado como JSON (`0.8`, `["a","b"]`, `{"seg_sex":"08:00-18:00"}`); texto sem
aspas vira string. Todos os campos são validados juntos com o resto da configuração; se qualquer um for inválido,
**nada é salvo** e a saída lista cada campo inválido com o valor anterior preservado (US5 cenário 3).

## Saídas

`create`:

```text
Empresa: clinica-sorriso (em_configuracao)            [novo | existente]
  [1/6] empresa           OK        0,1 s
  [2/6] configuracao      OK        0,1 s   campos alterados: 4
  [3/6] conexao           OK        0,1 s   instancia: clinica-sorriso
  [4/6] credenciais       OK        0,0 s   atualizadas
  [5/6] documentos        OK       12,4 s   3 ok, 0 inalterados, 0 falhas   custo_usd=0.000321
  [6/6] resumo            OK
Total: 12,8 s. Proximo passo: readiness clinica-sorriso
```

`readiness`:

```text
Prontidao de clinica-sorriso
  configuracao completa     OK
  documentos indexados      OK    3 documentos, 41 trechos
  conexao verificada        FALTA instancia desconectada (estado: desconectada)
  conversa de teste         FALTA nenhum teste aprovado depois da ultima alteracao
Resultado: REPROVADA (2 pendencias)
```

`activate` com pendência: mesma lista, uma linha final `Ativacao recusada.`, código `1`.

`purge`:

```text
Empresa encerrada ha 3 min (drenagem de 120 s cumprida).
Apagado: conversas=12 mensagens=48 documentos=3 trechos=41 usos=40 repasses=2 credenciais=1 conexoes=1 configuracao=1
Numero (instancia clinica-sorriso) liberado. Auditoria registrada.
```

Sem a confirmação exata do nome, ou antes da drenagem, o comando não apaga nada, explica o motivo e sai com `1`.
Contagens são só números (sem dado pessoal).

## Regras de estado

Implementadas em `core/tenancy/ciclo_vida.py` (tabela em [data-model.md](../data-model.md#tenants-alterada)).
Transição inválida: `Transicao invalida: ativo -> em_configuracao. Permitido a partir de ativo: suspenso, encerrado.`
Todo comando de mudança grava estado anterior, estado novo, operador e data em `audit_log` **na mesma transação**
da mudança.

## Ferramentas existentes (FR-021)

Os contratos da 001 mudam assim:

| Comando | Mudança |
|---|---|
| `python -m scripts.ingest_docs load|list|remove` | `--tenant SLUG` **obrigatório** (antes lia `PILOT_TENANT_ID`). Sem `--tenant` o comando falha com código 2 e não grava nada. Empresa encerrada: recusa (código 1) |
| `python -m scripts.run_evals --suite S` | `--tenant SLUG` obrigatório. Nova suíte `isolamento` com `--tenants a,b,c` (research R-14) |

`scripts/seed_tenant.py` é removido. `make seed` passa a rodar `scripts.tenants create` com `FILE=` obrigatório; os alvos
`make ingest` e `make evals` exigem `TENANT=`.

## Alvos do Makefile (resumo)

```text
make tenant-create FILE=docs/exemplos/empresa.yml OPERADOR=rafael
make tenant-readiness TENANT=clinica-sorriso OPERADOR=rafael
make tenant-activate  TENANT=clinica-sorriso OPERADOR=rafael
make tenant-suspend   TENANT=clinica-sorriso OPERADOR=rafael
make tenant-resume    TENANT=clinica-sorriso OPERADOR=rafael
```

## Testes (`tests/integration/test_onboarding.py`, `test_ciclo_vida.py`, `test_config_auditoria.py`, `test_exclusao_dados.py`)

- Arquivo inválido: nada criado, um erro por campo, saída 2.
- `create` interrompido (falha no passo de documentos) e repetido: uma empresa, uma conexão, documentos sem
  duplicar, estado `em_configuracao`.
- Duas empresas com o mesmo `instance_name`: segundo `create` recusado.
- `activate` com cada pendência isolada: recusado e listado.
- `suspend` e `resume`: mensagem durante a suspensão guardada e marcada, sem resposta.
- `config set` válido e inválido; auditoria com anterior, novo, operador e data; empresa B inalterada.
- `purge` sem confirmação, antes da drenagem e correto; contagens de A e B idênticas antes e depois.
- Saídas e logs de todos os comandos não contêm os valores de teste das credenciais.
