# ADR-0008: Agregação do painel em tabelas mantidas por job

- Status: aceita
- Contexto da feature: [specs/004-admin-dashboard](../../specs/004-admin-dashboard/plan.md)
- Refina: [ADR-0006](0006-leitura-entre-empresas-pela-api.md)

## Contexto

A visão geral do painel soma mensagens, handoffs e custo de todas as empresas, e precisa abrir em até 3 s com 1 milhão de
mensagens no histórico, com números no máximo 5 minutos defasados (SC-002, FR-042). O ADR-0006 propôs "views de agregação" lidas
por um papel `plantao_painel` sem acesso ao conteúdo. Ao desenhar, apareceram dois problemas:

1. As tabelas de negócio têm `FORCE ROW LEVEL SECURITY`, então uma visão (ou visão materializada) pertencente ao dono também é
   filtrada por `app.tenant_id` e enxergaria zero linhas, a menos que se crie uma exceção de RLS para o dono.
2. `usage_metrics` existe mas nenhum código a escreve (só `llm_calls` registra custo), e é diária, sem hora.

## Decisão

1. **Duas tabelas** com `tenant_id`: `painel_agregado_hora` (uma linha por empresa e hora) e `painel_situacao` (estado corrente
   por empresa). Detalhes em [data-model.md](../../specs/004-admin-dashboard/data-model.md).
2. **Um job ARQ** (`agregar_painel`, a cada 2 minutos) recalcula cada empresa **dentro de `tenant_session`**, lendo as tabelas de
   negócio sob RLS e gravando por upsert idempotente. Janela: últimas 3 horas e a hora corrente; uma execução diária refaz os 2
   últimos dias. Não há exceção de RLS para o dono nem papel que ignore RLS.
3. **Papel `plantao_painel`** continua como no ADR-0006 (só `SELECT`), com duas precisões: leitura das tabelas de negócio por
   **privilégio de coluna** (nunca `messages.conteudo`, `external_id`, `conversations.contato_*`, credenciais) e uma política
   `FOR SELECT TO plantao_painel USING (true)` em cada tabela lida, porque o RLS está forçado.
4. A visão geral e a lista leem **só** as tabelas `painel_*`; a ficha lê `painel_*` mais as tabelas de metadado liberadas.
5. `usage_metrics` não é usada nem alterada.

## Alternativas

- **Visões materializadas**: descartadas pelo problema 1 acima (exigiriam exceção de RLS para o dono, o que enfraquece o princípio III).
- **Consulta direta a cada abertura**: lenta com histórico grande e disputa o banco do atendimento.
- **Preencher `usage_metrics`**: exigiria mexer no caminho do atendimento (princípio II) e a granularidade diária não cobre "Hoje".
- **Banco ou réplica separada para análise**: custo operacional desproporcional para 1 a 5 operadores.

## Consequências

- Uma migração (`0005_painel`) e um job a mais para operar; se o worker cair, os números envelhecem (a tela avisa a partir de
  10 minutos e `GET /admin/saude` expõe a idade).
- Linhas agregadas sem texto, contato ou identificador de conversa; o `purge` da empresa as remove (acrescentar à lista de
  `core/tenancy/exclusao.py`).
- Correções tardias (mensagem gravada com atraso fora da janela de 3 h) só aparecem na execução diária; aceitável para um painel
  de operação.
- Se um dia houver centenas de empresas, o job pode ser fatiado por lote sem mudar o desenho.
