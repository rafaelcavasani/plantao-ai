# Contrato: Arquivo de configuração da empresa (onboarding)

Entrada de `python -m scripts.tenants create --file <arquivo.yml>`. Implementa FR-007, FR-008, FR-009, FR-012,
FR-013 e FR-005. Modelo pydantic: `ArquivoEmpresa` em `core/tenancy/onboarding.py` (`extra = "forbid"`: campo
desconhecido é erro, para pegar erro de digitação).

**Regra de ouro**: o arquivo **não contém segredos**. Credenciais entram por nome de variável de ambiente.

## Esquema

```yaml
# docs/exemplos/empresa-modelo.yml
slug: clinica-sorriso            # obrigatório; ^[a-z0-9]+(-[a-z0-9]+)*$, 3 a 63 caracteres; chave de idempotência
nome_empresa: "Clínica Sorriso"  # obrigatório; 2 a 255 caracteres
nicho: clinica_odontologica      # obrigatório
plano: recepcionista             # opcional; padrão "recepcionista"

configuracao:                    # opcional; qualquer campo omitido usa CONFIG_PADRAO
  tom_de_voz: "Cordial, acolhedor e direto. Trate o cliente por 'você'."
  horario_funcionamento:
    seg_sex: "08:00-18:00"
    sabado: "08:00-12:00"
  limite_desconto_percentual: 10.0
  topicos_proibidos: ["garantia de resultado", "diagnóstico"]
  confianca_minima_handoff: 0.7
  palavras_gatilho: ["processo", "procon", "cancelar tudo", "advogado", "reclamação"]
  router_confidence_threshold: 0.6
  min_similarity: 0.30
  handoff_ttl_minutos: 60
  limite_mensagens_por_minuto: 60

canal:                           # obrigatório
  tipo: whatsapp                 # único valor aceito nesta entrega
  provedor: evolution            # único valor aceito nesta entrega
  instance_name: clinica-sorriso # obrigatório; único em toda a plataforma
  api_key_env: SORRISO_EVOLUTION_API_KEY        # nome da variável de ambiente com a chave de envio
  webhook_secret_env: SORRISO_WEBHOOK_SECRET    # nome da variável com o segredo de entrega (>= 32 caracteres)

documentos:                      # opcional; pasta ou arquivos relativos ao arquivo YAML
  pasta: ./docs-sorriso

teste_prontidao:                 # opcional; usado por `tenants test`
  pergunta: "Qual o horário de sábado?"
  esperado: ["08:00", "12:00"]   # termos que a resposta deve conter (comparação normalizada)
```

## Validação (antes de qualquer escrita)

O comando valida o arquivo inteiro e, havendo erro, **não cria nada** e imprime um erro por campo
(`configuracao.confianca_minima_handoff: deve estar entre 0 e 1`). Código de saída 2.

| Campo | Regra |
|---|---|
| `slug` | padrão acima; imutável depois de criado (arquivo com `slug` existente e `nome_empresa` diferente atualiza o nome e audita) |
| `configuracao.*` | mesmas faixas de [data-model.md](../data-model.md#tenant_config-alterada); listas de textos não vazios; `horario_funcionamento` com valores `HH:MM-HH:MM` |
| `canal.api_key_env` / `webhook_secret_env` | variáveis precisam existir e não estar vazias; o segredo de entrega precisa ter pelo menos 32 caracteres. Mensagem de erro cita só o **nome** da variável |
| `canal.instance_name` | livre, ou já pertencente à mesma empresa. De outra empresa: recusado (FR-002) |
| `documentos.pasta` | precisa existir; extensões suportadas por `core/rag/chunking.py` (`.txt`, `.md`, `.pdf`) |
| `teste_prontidao.esperado` | lista de textos não vazios |

## Semântica de repetição (FR-013)

| Situação ao repetir o comando | Resultado |
|---|---|
| Empresa já existe (`slug`) | reutiliza; não cria outra; não altera o estado (empresa `ativo` continua `ativo`) |
| Configuração igual à salva | nenhum `UPDATE`, nenhuma linha em `audit_log` |
| Campo de configuração mudou | atualiza e grava uma linha de auditoria por campo (operador, anterior, novo) |
| Conexão já existe na mesma empresa | reutiliza; credenciais só são regravadas se o valor mudou (auditoria `credencial`: `"<atualizada>"`) |
| Documento com mesmo conteúdo | `INALTERADO`, sem custo de embedding |
| Documento alterado | nova versão (comportamento da 001) |
| Interrupção no meio | empresa permanece `em_configuracao`; o que já foi gravado permanece; repetir conclui o restante |

## Arquivos de exemplo (entregues em `docs/exemplos/`)

- `empresa-modelo.yml`: o esquema completo acima com comentários.
- `piloto.yml`: a clínica piloto, com `slug: clinica-sorriso-piloto` (o mesmo do backfill da migração 0004) e a
  configuração atual do piloto. Usado uma vez na migração (research R-15).
