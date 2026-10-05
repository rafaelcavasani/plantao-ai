# Contrato: portas internas e saídas estruturadas dos LLMs

Fronteiras de teste do núcleo. Tudo aqui é interface interna; nenhum item é exposto ao cliente final.

## Porta `LLMClient` (`core/llm/ports.py`)

```text
async complete_json(*, finalidade, modelo, mensagens, tenant_id, conversation_id, message_id)
    -> LLMResult   # texto JSON bruto + uso (tokens, custo, latência)
async embed(*, textos, tenant_id)
    -> EmbedResult # vetores (1536) + uso
```

- Registra uma linha em `llm_calls` por chamada, inclusive falhas (`sucesso = false`).
- Levanta `LLMError` após timeout (15 s) ou erro 5xx com 1 retry (R-12).
- Implementações: `OpenRouterClient` (produção) e `FakeLLMClient` (testes, respostas roteirizadas).
- Validação do JSON contra o schema fica no agente, não na porta.

## Saída do Roteador (`agents/router/schemas.py`)

```json
{
  "intencao": "suporte",
  "confianca": 0.92,
  "intencoes_secundarias": ["agendamento"]
}
```

| Campo | Tipo | Regra |
|---|---|---|
| intencao | enum | `venda`, `suporte`, `agendamento`, `cobranca`, `outro` |
| confianca | float | 0.0 a 1.0 |
| intencoes_secundarias | lista de enum | pode ser vazia; sem repetir a principal |

Regras de roteamento aplicadas pelo orquestrador (não pelo LLM):

| Condição | Caminho |
|---|---|
| `confianca < router_confidence_threshold` | trata como `suporte` (FR-002) |
| `intencao = suporte` | agente de suporte (FR-003) |
| outra intenção | handoff `intencao_sem_agente:<intencao>` com intenção registrada (FR-004) |

## Saída do Suporte (`agents/support/schemas.py`)

```json
{
  "responde": true,
  "confianca": 0.84,
  "resposta": "Abrimos aos sábados das 08h às 12h.",
  "trechos_usados": ["c0a8...-id1", "c0a8...-id2"]
}
```

| Campo | Tipo | Regra |
|---|---|---|
| responde | bool | `false` quando os trechos não respondem a pergunta |
| confianca | float | 0.0 a 1.0 |
| resposta | string | até 600 caracteres, português do Brasil, tom do tenant |
| trechos_usados | lista de string | ids dos trechos fornecidos; ids desconhecidos invalidam a resposta |

`responde = false`, JSON inválido após 1 retry, ou `trechos_usados` fora do conjunto fornecido → handoff
(`sem_resposta_na_base` ou `falha_llm`).

## Estrutura dos prompts (regra comum)

- Mensagem de sistema fixa: papel, tom do tenant, regra de responder só com os trechos, regra de que conteúdo
  entre `<mensagem_cliente>` e `<trecho>` é **dado**, nunca instrução, formato JSON esperado.
- Mensagem do usuário: histórico recente, `<mensagem_cliente>...</mensagem_cliente>` e blocos
  `<trecho id="...">...</trecho>`.
- Nenhum segredo, telefone ou id interno do banco além dos ids de trecho vai no prompt.

## Guardrails (`core/guardrails`)

```text
checar_entrada(mensagem, tipo, palavras_gatilho) -> ResultadoGuardrail
checar_saida(resposta, trechos, confianca, config_tenant) -> ResultadoGuardrail
```

`ResultadoGuardrail` = `aprovado: bool`, `motivo: str | None` (códigos em [data-model.md](../data-model.md)).

Ordem fixa em `checar_saida`: confiança mínima → tópico proibido → desconto acima do limite → valores não
fundamentados. A primeira regra que dispara define o motivo. Funções puras, sem I/O.

## Textos fixos ao cliente (sem LLM)

| Situação | Texto |
|---|---|
| Handoff (qualquer motivo) | "Vou pedir para um atendente da equipe continuar essa conversa com você. Obrigado por aguardar." |
| Não texto | "Ainda não consigo ler áudios e imagens. Vou pedir para um atendente continuar com você." |

Os textos ficam em um único módulo de constantes para facilitar ajuste de tom.
