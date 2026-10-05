# ADR-0003: Resolução da empresa pela conexão do canal

- Status: aceita
- Contexto da feature: [specs/002-multitenancy](../../specs/002-multitenancy/plan.md)

## Contexto

Até a spec 001 o webhook usava uma empresa fixa (`PILOT_TENANT_ID`) e um segredo global. Com várias empresas,
cada mensagem recebida precisa chegar à empresa certa antes de qualquer sessão com `app.tenant_id` existir, e
nenhuma empresa pode ser acionada por credencial de outra.

## Decisão

1. A chave de busca é o campo `instance` do corpo do webhook. Cada empresa tem uma linha em
   `channel_connections` com instância única.
2. A autenticação é feita com um segredo próprio da conexão, enviado no header `X-Webhook-Token`. O banco guarda
   só o hash sha256. Instância desconhecida e token errado devolvem a mesma resposta 401, para não revelar quais
   instâncias existem.
3. `channel_connections` tem leitura aberta (sem filtro por `app.tenant_id`) e escrita restrita à empresa dona.
   É a única tabela com essa exceção ao princípio III da constituição, porque o webhook precisa localizar a
   empresa antes de saber qual ela é. A tabela não guarda credenciais; elas ficam em `channel_credentials`, com
   RLS normal e valores cifrados.
4. Estado e configuração da empresa são lidos do banco a cada mensagem, sem cache. Uma suspensão vale na
   mensagem seguinte.
5. O worker confere o estado ao iniciar e de novo, sob trava advisory compartilhada, imediatamente antes de
   gravar a resposta. A mudança de estado usa a trava exclusiva com a mesma chave
   (`hashtextextended('estado_empresa:' || tenant_id, 0)`). Assim uma suspensão espera as respostas em curso e
   nenhuma resposta sai depois dela. Foi descartado `SELECT ... FOR SHARE` em `tenants`, porque exige privilégio
   de UPDATE que o papel `plantao_app` não tem.

## Consequências

- O webhook deixa de depender de configuração global; `PILOT_TENANT_ID`, `tenant_piloto()` e o segredo global
  são removidos.
- Cada leitura de estado custa uma consulta, aceitável para o volume do MVP.
- Pontos a confirmar com uma Evolution API real (tarefa T004): o corpo de `messages.upsert` traz `instance`; o
  `POST /webhook/set/{instance}` aceita header customizado; `GET /instance/connectionState/{instance}` devolve
  `state=open` quando conectada. Se algum falhar, aplicar a contingência de research R-02 ou R-10. Resultado
  da confirmação: pendente.
