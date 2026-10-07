# ADR-0007: Autenticação e papéis do operador do painel

- Status: aceita (resolve a clarificação 1 da spec 004)
- Contexto da feature: [specs/004-admin-dashboard](../../specs/004-admin-dashboard/spec.md)

## Contexto

Hoje o "operador" é um texto livre (`--operador`), então a auditoria não prova quem fez a mudança. O painel
precisa de identidade real e de dois papéis: **leitura** e **operação** (FR-001, FR-002, FR-003).

## Opções

1. Usuário e senha próprios: mais código e mais risco (hash, recuperação, bloqueio).
2. Login por provedor externo (OIDC, por exemplo Google): sem senha para guardar, uma lista de e-mails
   autorizados e o papel de cada um.
3. Só proteção por rede/VPN, perfil único: não distingue quem fez, não serve de auditoria. Aceitável apenas
   como etapa provisória.

## Decisão

Opção 2, com lista de operadores e papéis em configuração (variável de ambiente ou tabela `operadores`, a
decidir no plano). Sessão por cookie `HttpOnly`, `Secure` e `SameSite=Lax`, com expiração por inatividade
(FR-006). A API checa o papel em toda rota de escrita, mesmo que o botão nem apareça (FR-002). A identidade
(e-mail) é o que vai para `audit_log.operador`.

## Consequências

- Nova dependência de provedor de identidade; justificar no plano (princípio VIII).
- Sem operador autorizado, nada é exibido; a primeira inclusão de operador é feita por configuração, não pela UI.
- A visão de cliente (dono da empresa) fica fora; teria outro modelo de acesso.
