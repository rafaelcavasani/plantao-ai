# Contrato: Webhook de entrada do WhatsApp por conexão

Altera [o contrato da 001](../../001-router-support-agent/contracts/whatsapp-webhook.md). Implementa FR-001, FR-003,
FR-006, FR-016, FR-017, FR-026 e SC-009. O formato do corpo e as regras de parse não mudam, com uma adição: o
campo `instance`.

## `POST /webhooks/whatsapp`

**Identificação**: o campo `instance` do corpo (nome da instância da Evolution) identifica a conexão. Ele é usado
só como chave de busca em `channel_connections`.

**Autenticação**: header `X-Webhook-Token` comparado em tempo constante com o segredo **da conexão encontrada**
(`sha256(token)` contra `channel_credentials.webhook_secret_hash`). O segredo global `WHATSAPP_WEBHOOK_SECRET` deixa
de existir. Configure no webhook de cada instância da Evolution o header com o segredo daquela empresa.

**Corpo** (adição em relação à 001):

```json
{
  "event": "messages.upsert",
  "instance": "clinica-sorriso",
  "data": {
    "key": { "remoteJid": "5511999990000@s.whatsapp.net", "fromMe": false, "id": "3EB0A1B2C3D4" },
    "message": { "conversation": "Qual o horário de sábado?" }
  }
}
```

Corpo sem `instance` ou com valor que não é string: tratado como instância desconhecida (401).

## Ordem de processamento

1. Ler o corpo JSON (objeto). Corpo inválido: `422`.
2. Buscar a conexão por `instance` no diretório (sessão sem tenant). Não encontrada: calcular um hash falso e seguir
   para o passo 3 com falha.
3. Conferir o token com o segredo da conexão. Falha: `401`.
4. `definir_contexto(tenant_id, correlation_id)` e ler `tenants.status` e `tenant_config` (uma transação).
5. Aplicar o estado da empresa (tabela abaixo).
6. Aplicar o limite por minuto da empresa (`limite_mensagens_por_minuto`).
7. Persistir conversa e mensagem; enfileirar `processar_mensagem(tenant_id, message_id, correlation_id)` com
   `_job_id = "{tenant_id}:{message_id}"`.

O `parse_inbound` continua ignorando `fromMe`, grupos, status e eventos que não são mensagem **depois** da
autenticação (entrega não autenticada nunca chega ao parse).

## Respostas

| Status | Corpo | Quando |
|---|---|---|
| 200 | `{"status":"queued"}` | empresa ativa, mensagem nova persistida e enfileirada |
| 200 | `{"status":"duplicate"}` | `(tenant_id, external_id)` já existe (FR-025: por empresa) |
| 200 | `{"status":"ignored"}` | evento ignorado pelo parse; empresa em configuração ou encerrada (nada é gravado) |
| 200 | `{"status":"suspended"}` | empresa suspensa: mensagem gravada com `recebida_em_suspensao`, sem job (FR-017) |
| 200 | `{"status":"rate_limited"}` | empresa acima do seu limite; só ela é limitada (FR-026) |
| 401 | `{"detail":"invalid token"}` | token ausente, token errado, instância desconhecida ou sem `instance` (indistinguíveis) |
| 422 | detalhe de validação | corpo que não é JSON objeto |

200 em duplicata, ignorada, suspensa e limite excedido evita retentativa agressiva do provedor.

**Efeitos por estado**

| Estado | Grava mensagem | Enfileira | Resposta automática |
|---|---|---|---|
| em_configuracao | não | não | não |
| ativo | sim | sim | sim |
| suspenso | sim (marcada) | não | não |
| encerrado | não | não | não |

**Registros técnicos** (sem telefone nem conteúdo, FR-006):

| Evento | Nível | Campos |
|---|---|---|
| `conexao_desconhecida` | warning | `instance` truncada em 64 caracteres e sanitizada; sem `tenant_id` |
| `token_invalido` | warning | `tenant_id` da conexão encontrada |
| `empresa_nao_ativa` | info | `tenant_id`, `status` |
| `rate_limited` | warning | `tenant_id` |
| `mensagem_enfileirada` | info | `tenant_id`, `correlation_id` |

## `GET /webhooks/whatsapp`

Verificação da Meta Cloud API, sem alteração (usa `WHATSAPP_VERIFY_TOKEN`, que não é segredo por empresa).

## Job `processar_mensagem(tenant_id, message_id, correlation_id)`

Assinatura inalterada. Passa a devolver, além dos códigos atuais (`respondida`, `handoff`, `ja_respondida`,
`handoff_ativo`, `mensagem_inexistente`), os códigos `empresa_inativa` (estado diferente de `ativo` no início ou na
gravação) e `falha_canal` (envio recusado: resposta com `status_envio = falha` e handoff). O `tenant_id` do job só
vale se a mensagem existir **dentro** desse tenant (RLS); caso contrário `mensagem_inexistente`.

## Testes de contrato (`tests/contract/test_webhook.py`)

- Token da empresa A com `instance` da empresa B: 401, nada gravado em B (SC-009).
- Instância desconhecida e token errado: mesmo status e mesmo corpo.
- Empresa ativa, suspensa, em configuração e encerrada: tabela de efeitos acima.
- Mesmo `external_id` em duas empresas: ambas `queued`, uma única resposta cada.
- Limite excedido em A não altera a resposta de B.
- Nenhum log do webhook contém telefone, conteúdo, token ou chave de envio.
