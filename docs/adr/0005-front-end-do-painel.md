# ADR-0005: Onde mora o front-end do painel e como ele fala com o sistema

- Status: aceita
- Contexto da feature: [specs/004-admin-dashboard](../../specs/004-admin-dashboard/spec.md)

## Contexto

A spec 004 pede um painel web para o operador da plataforma. A constituição lista `apps/` com `api`, `worker` e
`dashboard`, e `apps/dashboard/` já existe como espaço reservado para o painel interno. Um diretório de topo novo
exigiria ADR (Restrições Adicionais); usar o que já existe não.

## Decisão

1. O front-end vive em `apps/dashboard/`, sem criar diretório de topo. Código Python e código do front-end não se
   misturam: o front-end fica em `apps/dashboard/web/`, com build próprio.
2. O front-end só fala com a API (`apps/api`), nunca com o banco. A API expõe as rotas de operação sob
   `/admin/*`, validadas com pydantic (princípio IV).
3. A identidade visual é a do `design-system/` (tema escuro, acento teal). O protótipo
   `design-system/plantao-admin.html` é referência visual, não código reaproveitado.
4. A escolha de framework de front-end, bibliotecas de gráfico e hospedagem fica para o `plan.md` da spec 004,
   com justificativa de cada dependência nova (princípio VIII). Gráficos simples podem ser SVG próprio, como no
   protótipo, para não adicionar biblioteca.

## Consequências

- Nenhum diretório de topo novo; a regra de camadas (`apps → agents → core → db`) não muda.
- O front-end pode ser entregue separado da API (arquivos estáticos), mas o contrato `/admin/*` precisa ser
  versionado junto com a spec.
- O docstring de `apps/dashboard/__init__.py` ("Streamlit/Retool") deixa de valer; atualizar na implementação.
