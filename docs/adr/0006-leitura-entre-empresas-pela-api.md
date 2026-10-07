# ADR-0006: Como a API lê e altera dados entre empresas para o painel

- Status: aceita (refinada pelo [ADR-0008](0008-agregacao-do-painel.md): tabelas agregadas mantidas por job no lugar de views)
- Contexto da feature: [specs/004-admin-dashboard](../../specs/004-admin-dashboard/spec.md)

## Contexto

O painel precisa de agregações entre empresas (visão geral) e de ações de operação (suspender, retomar,
encerrar). Hoje isso só existe em `scripts/`, via `db/admin.py`, cujo papel ignora RLS e que `apps/` não pode
importar. A constituição (princípio III) exige filtro por `tenant_id` e RLS como segunda camada.

## Opções

1. **Papel administrativo na API.** Simples, mas põe um papel que ignora RLS dentro do processo web. Um erro numa
   rota expõe todas as empresas. Descartada.
2. **Papel de leitura dedicado, só com agregações.** A API usa um papel `plantao_painel` sem acesso às tabelas
   de conteúdo (`messages.conteudo`, contatos, credenciais). Ele lê apenas views de agregação por empresa e
   período (contagens, somas, último horário). Dado pessoal não está ao alcance dele.
3. **Painel lê pelo papel normal, empresa por empresa.** Mantém RLS, mas a visão geral viraria N consultas e não
   há como somar entre empresas no banco.

## Decisão

- **Leitura:** opção 2. As views são criadas por migração Alembic reversível; o papel recebe só `SELECT` nelas e
  em `tenants`, `channel_connections` (sem credenciais), `readiness_checks` e `audit_log`.
- **Escrita:** mudança de estado, configuração e conexão reutiliza os serviços de `core/tenancy/` com uma sessão
  administrativa criada apenas num módulo da API (`apps/api/admin/`). Um contrato do import-linter permite que
  só esse módulo importe `db.admin`; qualquer outro `apps/` continua proibido.
- **Auditoria:** o operador gravado vem da sessão autenticada (ADR-0007), nunca de parâmetro livre.
- **Teste de isolamento (princípio III):** teste com duas empresas garantindo que as views somam certo e que o
  papel `plantao_painel` não consegue ler `messages.conteudo`.

## Consequências

- O painel só lê metadados de conversa (clarificação de 2026-10-06 na spec 004): o papel `plantao_painel` não precisa, e não deve ter, acesso a `messages.conteudo` nem a `conversations.contato_*`. Se um dia for preciso ver conteúdo, exigirá nova decisão e outro papel, com auditoria.
- Mais uma migração e um papel de banco a manter; em troca, o raio de dano de um bug na API de leitura é só de
  agregados.
