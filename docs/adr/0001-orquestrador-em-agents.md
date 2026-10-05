# ADR-0001: Orquestrador LangGraph em `agents/orchestrator`

- Status: aceita
- Data: 2026-10-04
- Contexto da feature: [specs/001-router-support-agent](../../specs/001-router-support-agent/plan.md)

## Contexto

No Sprint 1 o grafo do orquestrador ficou em `core/orchestrator/` e importava `agents/router/agent.py`.
A constituição (princípio II) define a regra de dependência `apps > agents > core > db` e proíbe que `core`
importe `agents`. O grafo precisa compor agentes, então não pode viver em `core`.

## Decisão

Mover o grafo e o estado para `agents/orchestrator/`. O pacote `core` fica sem conhecimento de agentes e
guarda só serviços transversais (LLM, RAG, guardrails, handoff, segurança, observabilidade). Somente
`agents/orchestrator` compõe `agents/router` e `agents/support`; os dois agentes não se importam.

A regra é imposta no CI por `import-linter` (arquivo `.importlinter`, 4 contratos).

## Consequências

- Imports antigos `core.orchestrator.*` deixam de existir. Nenhum código fora do Sprint 1 os usava.
- O grafo recebe suas dependências (cliente LLM, busca de trechos, configuração) por injeção, o que
  permite testar com fakes sem rede.
- Os próximos agentes (agendador, SDR, cobrança) entram como novos nós em `agents/orchestrator/graph.py`.
