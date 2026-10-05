# Contrato: CLI de ingestão de conhecimento

Implementa FR-011 e FR-012. Executado pelo operador (mesma pessoa que o desenvolvedor, conforme Assumptions).

## Comando

```text
python -m scripts.ingest_docs <subcomando> [opções]
```

O tenant é sempre `PILOT_TENANT_ID`. Não há opção `--tenant` neste sprint (evita erro operacional; multi-tenant
real no Sprint 3).

## Subcomandos

### `load <caminho>`

Carrega um arquivo ou todos os arquivos suportados (`.txt`, `.md`, `.pdf`) de uma pasta.

| Situação | Comportamento |
|---|---|
| Documento novo | cria `knowledge_documents`, gera trechos e embeddings |
| Documento existente com mesmo `content_hash` | ignora e informa `inalterado` |
| Documento existente com conteúdo diferente | substitui trechos antigos na mesma transação, `versao += 1` (FR-012) |
| PDF sem texto extraível | não indexa; informa `sem_texto` |
| Extensão não suportada | ignora e informa `nao_suportado` |
| Falha de embedding | aborta o documento, mantém a versão anterior intacta (transação) |

Saída por documento (uma linha, sem conteúdo do arquivo):

```text
faq_clinica.md  OK  versao=2  trechos=18  tokens_embedding=5120  custo_usd=0.000102
```

Código de saída: `0` se nenhum documento falhou; `1` se algum falhou.

### `list`

```text
nome_origem        versao  trechos  atualizado_em
faq_clinica.md          2       18  2026-10-04T14:03:11Z
```

### `remove <nome_origem>`

Remove o documento e seus trechos. Pede confirmação (`--yes` para pular).

## Garantias

- Operação atômica por documento: ou a nova versão entra inteira, ou a antiga permanece.
- Cada chamada de embedding gera linha em `llm_calls` (`finalidade = embedding`).
- Conteúdo do documento é tratado como dado; nunca é executado nem interpretado como instrução (FR-013).
- Tamanho máximo por arquivo: 5 MB (acima disso, `arquivo_grande`).
- Nenhum dado do arquivo vai para logs; só nome, contagens e custo.
