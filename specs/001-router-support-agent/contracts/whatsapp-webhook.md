# Contrato: Webhook de entrada do WhatsApp

Implementa FR-014, FR-015, FR-016 e as exigências do princípio IV da constituição.

## `POST /webhooks/whatsapp`

**Autenticação**: header `X-Webhook-Token` com valor igual a `WHATSAPP_WEBHOOK_SECRET`, comparado em tempo
constante. Configure o mesmo valor no cabeçalho customizado do webhook da Evolution API.

**Corpo (formato Evolution API usado hoje por `parse_inbound`)**:

```json
{
  "event": "messages.upsert",
  "data": {
    "key": { "remoteJid": "5511999990000@s.whatsapp.net", "fromMe": false, "id": "3EB0A1B2C3D4" },
    "message": { "conversation": "Que horas vocês abrem no sábado?" }
  }
}
```

**Regras de parse**

| Condição | Resultado |
|---|---|
| `fromMe = true` ou evento que não é mensagem | `200 {"status":"ignored"}` |
| Texto em `message.conversation` ou `message.extendedTextMessage.text` | `tipo = texto` |
| Qualquer outro tipo de mensagem (áudio, imagem, documento, figurinha) | `tipo = nao_texto`, `conteudo = ""` |
| Sem `key.id` ou sem `remoteJid` | `200 {"status":"ignored"}` com log de aviso |

**Respostas**

| Status | Corpo | Quando |
|---|---|---|
| 200 | `{"status":"queued"}` | mensagem nova persistida e enfileirada |
| 200 | `{"status":"duplicate"}` | `(tenant_id, external_id)` já existe (FR-015) |
| 200 | `{"status":"ignored"}` | ver tabela de parse |
| 200 | `{"status":"rate_limited"}` | tenant acima de `RATE_LIMIT_MSGS_PER_MIN` (padrão 60) |
| 401 | `{"detail":"invalid token"}` | token ausente ou incorreto |
| 422 | detalhe de validação | corpo que não é JSON objeto |

O status 200 em duplicata, ignorada e limite excedido evita retentativas agressivas do provedor.
O endpoint **não** chama LLM e deve responder em menos de 500 ms (FR-016).

**Efeitos**: grava a mensagem (`remetente = lead`) e atualiza `ultima_atividade_em`; enfileira o job
`processar_mensagem(message_id)`. O telefone nunca entra na fila.

## `GET /webhooks/whatsapp`

Verificação de webhook da Meta Cloud API. Mantida sem alteração (`hub.mode`, `hub.challenge`,
`hub.verify_token`). Não é usada pela Evolution API.

## Porta de saída: `MessageChannel` (`core/ports/channel.py`)

```text
async send_text(contato: str, texto: str) -> None
```

- Levanta `ChannelError` em falha de rede ou resposta não 2xx; o job converte em `status_envio = falha`.
- Implementada por `integrations/whatsapp/client.py`. Nenhum código de `agents/` ou `core/` depende de
  Evolution API.

## Testes de contrato (`tests/contract/`)

- `parse_inbound`: texto simples, texto estendido, áudio, imagem, `fromMe`, payload sem `id`.
- Token ausente, inválido e válido.
- Duplicata devolve `duplicate` sem enfileirar.
- `send_text` com resposta 2xx, 4xx e timeout.
