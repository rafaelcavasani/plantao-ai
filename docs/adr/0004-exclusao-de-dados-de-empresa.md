# ADR-0004: Exclusão de dados de uma empresa encerrada

- Status: aceita
- Contexto da feature: [specs/002-multitenancy](../../specs/002-multitenancy/plan.md)

## Contexto

Uma empresa encerrada pode pedir a remoção dos seus dados (LGPD). A remoção precisa ser completa, não pode
atingir outras empresas e precisa deixar prova de que ocorreu, sem manter dado pessoal.

## Decisão

1. A exclusão só é permitida para empresas `encerrado` e exige confirmação explícita do operador.
2. Antes de apagar há uma drenagem de `PURGE_DRENAGEM_SEGUNDOS` (padrão 120; 0 nos testes), para que jobs já
   iniciados terminem. Como o estado `encerrado` já impede novas respostas, nada novo entra durante a espera.
3. As tabelas da empresa são apagadas em ordem de chave estrangeira, dentro de uma transação por
   `tenant_session`, de modo que a RLS garante que só linhas dessa empresa são tocadas.
4. A linha em `tenants` permanece como marca (`dados_apagados_em` preenchido), sem dado pessoal, para manter
   a identidade (`slug`) reservada e provar a exclusão.
5. `audit_log` não tem chave estrangeira para `tenants` e é só de inclusão (INSERT e SELECT), de forma que os
   registros sobrevivem à exclusão. Os detalhes gravados nele não contêm dado pessoal nem segredo.
6. O CLI de operação usa o papel administrativo do banco, que é uma exceção declarada ao princípio III,
   restrita a `scripts/`.

## Consequências

- A exclusão é irreversível; a proteção está na exigência do estado `encerrado` e na confirmação.
- A trilha de auditoria cresce sem limite; uma política de retenção fica para uma spec futura.
- Backups do banco continuam fora do alcance desta decisão.
