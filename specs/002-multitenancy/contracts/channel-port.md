# Contrato: Porta `MessageChannel` por conexão

Altera [a porta da 001](../../001-router-support-agent/contracts/whatsapp-webhook.md#porta-de-saída-messagechannel-coreportschannelpy).
Implementa FR-004, FR-005 e FR-027. Arquivo: `core/ports/channel.py`. Nenhum código de `agents/` ou `core/` depende
de provedor concreto.

## Tipos

```text
@dataclass(frozen=True)
class ConexaoCanal:
    tenant_id: UUID
    canal: str              # "whatsapp"
    provedor: str           # "evolution"
    instance_name: str
    api_key: str = field(repr=False)   # chave de envio já descriptografada, só em memória

class EstadoConexao(StrEnum):
    CONECTADA = "conectada"
    DESCONECTADA = "desconectada"
    DESCONHECIDA = "desconhecida"
```

`ConexaoCanal` nunca é serializada, logada ou colocada em fila. É montada pelo job a partir de
`channel_connections` + `channel_credentials` (descriptografando `api_key_enc`) e descartada ao fim do envio.

## Porta

```text
class MessageChannel(Protocol):
    async def send_text(self, conexao: ConexaoCanal, contato: str, texto: str) -> None:
        """Envia texto pela conexão da empresa. Levanta ChannelError em falha."""

    async def verificar(self, conexao: ConexaoCanal) -> EstadoConexao:
        """Consulta o estado da instância no provedor (item 3 da prontidão). Não levanta por estado
        desconectado; levanta ChannelError só em falha de rede ou resposta inesperada."""
```

`ChannelError` mantém os códigos curtos atuais (`http_401`, `http_404`, `ConnectError`, `provedor_nao_implementado:<x>`).
O código nunca contém a credencial.

## Implementação `integrations/whatsapp/client.py`

| Ponto | Regra |
|---|---|
| Cliente HTTP | um `httpx.AsyncClient` compartilhado; a credencial vai em cabeçalho por chamada |
| `send_text` | `POST {WHATSAPP_BASE_URL}/message/sendText/{instance_name}` com header `apikey` da conexão (corpo igual ao atual) |
| `verificar` | `GET {WHATSAPP_BASE_URL}/instance/connectionState/{instance_name}` com header `apikey`; `state == "open"` vira `CONECTADA`. **Confirmar** o formato na Evolution real (research R-02, R-10) |
| `parse_inbound` | devolve `MensagemEntrada` com o novo campo `instance` (string vazia se ausente) |
| Timeout e erro | timeout de 10 s mantido; falha vira `ChannelError`; sem retry nesta entrega |

## Uso no worker

```text
conexao = await carregar_conexao(session, tenant_id, canal)      # core/tenancy/resolucao.py
try:
    await channel.send_text(conexao, contato, decisao.texto)
except ChannelError as exc:
    status_envio = "falha"
    registrar_handoff(motivo="falha_canal", ...)                 # só desta empresa
    logger.error("canal_falhou", extra={"dados": {"erro": str(exc)}})
```

Uma empresa sem conexão ou sem credencial no momento do envio também gera `falha_canal`.

## Testes de contrato (`tests/contract/test_whatsapp_channel.py`)

- `send_text` com 2xx, 4xx (401 vira `http_401`) e timeout, usando a credencial **da conexão** passada.
- Duas conexões diferentes no mesmo cliente enviam headers `apikey` diferentes (sem vazamento entre chamadas).
- `verificar`: `open`, `close`, instância inexistente (404) e erro de rede.
- `repr(ConexaoCanal)` e `str(ChannelError)` não contêm `api_key`.
- `parse_inbound` extrai `instance` e continua ignorando `fromMe`, grupos e status.
- `FakeChannel` (tests/fakes) registra `(instance_name, contato, texto)` e permite falha por `instance_name`.
