# Runbook de incidente por empresa

Pausar, investigar e retomar UMA empresa sem afetar as outras. Cada comando abaixo recebe o `slug` da empresa e
`--operador` (quem executa; vai para a auditoria). Código de saída 0 é sucesso; 1 é operação recusada.

## 1. Pausar rapidamente

```
make tenant-suspend TENANT=<slug> OPERADOR=<seu nome> MOTIVO="texto curto"
# equivalente: python -m scripts.tenants suspend <slug> --operador <nome> --motivo "texto curto"
```

Só vale para empresa `ativo`. Qualquer outro estado devolve `Transicao invalida: ...` e nada muda.

### O que acontece com a empresa suspensa

| Onde | Efeito |
|---|---|
| Webhook (mensagem nova) | Responde `200 {"status":"suspended"}`. A mensagem é gravada na conversa com `recebida_em_suspensao = true` e **não** vai para a fila. Nenhuma resposta automática sai. |
| Fila (job já enfileirado antes da suspensão) | O worker lê o estado no começo do job. Se não for `ativo`, devolve `empresa_inativa` e não chama o LLM nem o canal. |
| Resposta em andamento (grafo rodando) | Antes de gravar, o worker pega a trava compartilhada do estado e lê o estado de novo. Se a empresa já não está `ativo`, não grava nem envia. A suspensão espera quem já estava gravando terminar. |
| Resposta já gravada e em envio | Pode sair. É uma janela de milissegundos a poucos segundos (research R-06). |
| Demais empresas | Sem efeito: o estado, as filas lógicas e os contadores de limite são por empresa. |

A meta é nenhuma resposta nova em até 1 minuto (SC-004); na prática, vale a partir do próximo job.

Repasses para humano, conversas e documentos da empresa suspensa continuam no banco e legíveis.

### Confirmar

```
make tenant-status TENANT=<slug>     # Estado: suspenso
python -m scripts.tenants audit <slug>   # linha `estado/status` ativo -> suspenso, operador, data e motivo
```

## 2. Retomar

```
make tenant-resume TENANT=<slug> OPERADOR=<seu nome>
```

Só vale para empresa `suspenso`. Uma empresa `em_configuracao` não é retomada: ela é ativada com
`tenant-activate`, que exige a prontidão aprovada.

- Mensagens novas voltam a ser respondidas imediatamente.
- Mensagens recebidas durante a suspensão **não** são reprocessadas: ficam no histórico com a marca
  `recebida_em_suspensao`. Isso evita uma rajada de respostas atrasadas e fora de contexto. Se o cliente ainda
  precisa de resposta, um humano responde.
- O histórico, os documentos e a configuração ficam como estavam.

## 3. Investigar

1. `python -m scripts.tenants audit <slug>`: o que mudou, quando e por quem (configuração, estado, conexão, dados).
2. Conversas e repasses da empresa: consultar com `tenant_session` ou pelo papel administrativo, filtrando por
   `tenant_id`. Não copie texto de cliente final para chamados, e-mails ou logs (FR-005).
3. Mudança de configuração suspeita: corrija com `python -m scripts.tenants config set <slug> campo=valor
   --operador <nome>`; vale na próxima mensagem, sem reiniciar.
4. Canal com problema: `make tenant-readiness TENANT=<slug> OPERADOR=<nome>` verifica a conexão. Falha de envio em
   uma empresa vira repasse só nela (`falha_canal`).

## 4. Encerrar e apagar dados

`encerrado` é definitivo. Para apagar os dados da empresa (exclusão com confirmação do nome exato e trilha de
auditoria preservada), use os comandos `close` e `purge` de `scripts/tenants.py`. Detalhes e ordem na seção de
exclusão do `README.md`.

## 5. Ordem de deploy da migração 0004 (research R-15)

A migração `0004_multitenancy` só mexe em schema e em dados que não dependem de segredo. Ela **não** cria a conexão
de canal da empresa piloto. Entre a migração e o passo 3 abaixo, o webhook responde 401 (instância sem conexão).
Faça os três passos no mesmo deploy, com a Evolution API parada ou aceitando reentrega:

1. Parar API e worker.
2. `alembic upgrade head` (usa `DATABASE_ADMIN_URL`).
3. `python -m scripts.tenants create --file docs/exemplos/piloto.yml --operador <nome>`: encontra a piloto pelo
   `slug`, mantém `ativo`, adiciona conexão e credenciais e deixa os documentos `inalterado`.
4. Subir API e worker.

Se algo falhar, `alembic downgrade 0003` desfaz o schema e restaura os valores antigos de `status`.

## 6. Papel administrativo em produção (research R-16)

API e worker conectam como `plantao_app` (RLS, sem `BYPASSRLS`). Os comandos de `scripts/tenants.py` que operam
entre empresas usam `DATABASE_ADMIN_URL`, e esse papel precisa **ignorar RLS**: no Docker local é superusuário; em
produção, um papel com `BYPASSRLS`. Sem isso, os comandos não enxergam as linhas de outras empresas. Nunca use
`DATABASE_ADMIN_URL` na API ou no worker, e nunca guarde o segredo desse papel no mesmo ambiente que a aplicação
expõe à internet.
