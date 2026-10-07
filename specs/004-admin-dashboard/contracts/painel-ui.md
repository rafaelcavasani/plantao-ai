# Contrato: interface do painel

Define rotas, telas, estados e regras de interface que a implementação deve cumprir. Referência visual:
`design-system/plantao-admin.html` (FR-031). Este contrato não repete o CSS; fixa o comportamento.

## Rotas (hash, sem recarregar)

| Rota | Tela | Papel mínimo | Dados |
|---|---|---|---|
| `#/` | Visão geral | leitura | `GET /admin/visao-geral`, `GET /admin/empresas` |
| `#/empresas` | Gestão de empresas | leitura | `GET /admin/empresas` |
| `#/empresas/nova` | Nova empresa | operação | `GET /admin/planos` |
| `#/empresa/<slug>` | Ficha | leitura | `GET /admin/empresas/{slug}`, `/serie`, `/auditoria` |
| `#/empresa/<slug>/editar` | Editar empresa | operação | ficha + `/configuracao` + `/planos` |
| `#/empresa/<slug>/conversas` | Conversas (P3) | leitura | `GET /admin/empresas/{slug}/conversas` |
| sem sessão | Login | — | `GET /admin/eu` falha com 401 → `GET /admin/auth/entrar` |

Rota desconhecida ou empresa inexistente: "Empresa não encontrada" com volta para a lista. Papel `leitura` abrindo rota de
operação (mesmo por endereço direto): aviso "O papel de leitura não permite esta ação" e nenhum formulário.

## Estrutura (todas as telas)

- `div.app` = `aside.sidebar` + `main.content` (`header.topbar` + conteúdo). Navegação **só** na barra lateral, vertical,
  recolhível (240 px ↔ 64 px, rótulo ao passar o mouse quando recolhida). Abaixo de 1200 px começa recolhida; abaixo de
  768 px vira menu sobreposto com botão de abrir na topbar (FR-033).
- Topbar: título, "Atualizado há X" (texto simples), período (`Hoje`, `7d`, `30d`, só na visão geral) e `Exportar` (só na visão
  geral e na lista).
- Rodapé da barra lateral: avatar, e-mail (parte antes do `@`), papel e botão **Sair**.

## Estados obrigatórios de cada bloco (FR-027)

| Estado | Comportamento |
|---|---|
| Carregando | esqueleto no formato do bloco (nunca tela em branco) |
| Vazio | mensagem específica ("Nenhuma empresa encontrada", "sem mensagens") e, quando fizer sentido, a ação para resolver |
| Erro | mensagem curta + botão "Tentar de novo" **só naquele bloco**; os outros continuam visíveis |
| Desatualizado | `desatualizado = true` ou `atualizado_em` > 10 min: aviso âmbar no topo do bloco |
| Sem permissão | texto e ícone de cadeado; nunca botão desabilitado sem explicação |

Cor nunca é o único sinal (FR-032): todo estado, alerta e variação leva texto ou ícone (seta, triângulo, cadeado). Contraste
do texto no fundo escuro: AA.

## Visão geral

1. Quatro KPIs: Mensagens, Conversas, Taxa de handoff, Custo (US$), cada um com variação contra o período anterior de mesma
   duração (seta + valor + "vs período anterior"), sparkline e count-up. A margem total aparece como linha de apoio no
   KPI de custo ("Margem estimada US$ X" ou "margem indisponível").
2. Linha do tempo: recebidas e respondidas pelo agente (granularidade do contrato da API). O último ponto de cada série tem
   marca fixa que só pulsa em escala e opacidade; trocar o período reposiciona a marca sem animar o trajeto.
3. Donut "Empresas por estado" (um `circle` por estado sobre a mesma circunferência; centro mostra o estado líder e o total).
4. Funil de atendimento em escala **relativa por etapa** (nenhuma barra abaixo de 20% da largura), com a taxa entre etapas.
5. "Atenção ao vivo": uma linha por empresa que está em `atencao`, ordenada por gravidade, com ícone, texto do motivo e
   link para a ficha. Sem alertas: "Nenhuma empresa precisa de atenção agora".
6. Tabela de empresas (a mesma da gestão, com busca, filtro por estado e ordenação), 25 por página.
7. Botão "Atualizar" ao lado de "Atualizado há X": chama `POST /admin/atualizar` e consulta `/admin/saude` até mudar; mostra
   "Atualizando..." e desabilita por 30 s.

## Gestão de empresas (lista)

Colunas: Empresa (nome + slug), Nicho, Plano, Estado, Conexão, Documentos, Criada em, Ações (`Ver`, `Editar`). `Editar` some para
empresa encerrada e para o papel `leitura`. Botão `Nova empresa` só para `operacao`. Busca por nome ou slug, filtro por estado,
paginação do servidor. O ícone de atenção ao lado do nome tem texto alternativo com o motivo.

## Ficha

Cabeçalho: nome, badge de estado, slug, nicho, plano, alertas de atenção e as ações de `acoes_permitidas` (a tela **nunca** calcula
transições; usa o que a API devolve). Blocos: identificação e conexão (credenciais só como "configuradas"/"pendentes"),
prontidão (itens com ícone), atendimento do período, custo por finalidade e modelo com margem, gráficos, histórico de auditoria
paginado. Empresa com dados apagados: blocos de atendimento mostram "dados apagados em <data>".

### Ações de estado

Confirmação em janela modal com foco preso e `Esc` para cancelar:
- Suspender e Encerrar: campo de motivo opcional (vai para a auditoria).
- Encerrar: o botão de confirmar só habilita quando o campo recebe **exatamente** o nome da empresa (FR-007).
- Ativar de `em_configuracao`: se a API responder `prontidao_reprovada`, a janela lista os itens pendentes e não ativa.
- 409 `transicao_invalida` ou `conflito_versao`: mensagem com o estado atual e recarga da ficha.

## Formulário (nova e editar)

Blocos, na ordem: Identificação; Configuração do atendimento; Conexão do canal; Base de conhecimento. Rodapé fixo com
Cancelar e Criar/Salvar.

| Regra | Comportamento |
|---|---|
| Slug | sugerido a partir do nome (minúsculas, sem acento, hífen) até o operador editar; **somente leitura** na edição (FR-036) |
| Validação | no campo, ao enviar, com o foco indo ao primeiro erro; **repetida no servidor**, cujos erros (`campos`) são mostrados no mesmo lugar (FR-035) |
| Horário | sete campos `HH:MM-HH:MM` ou `fechado` |
| Credenciais (edição) | mostra "configuradas" e **nunca** o valor; só aceita novos valores depois de "Substituir credenciais" (FR-038); aviso de que exigirá nova verificação |
| Segredo de entrega | campo mascarado com "Gerar" (48 caracteres hexadecimais, `crypto.getRandomValues`) e alternar visibilidade; ≥ 32 caracteres |
| Documentos | lista com nome e tamanho, remoção antes de salvar, recusa de formato ou tamanho inválido e de nomes repetidos; depois do envio, mostra o resultado por arquivo da remessa (FR-041) |
| Edição simultânea | corpo vai com `versao`; em 409 `conflito_versao` mostra o conflito com os valores atuais e deixa escolher entre recarregar ou reaplicar (FR-040) |
| Sem alterações | "Nenhuma alteração para salvar" sem chamar a API |
| Saída com edição pendente | pergunta antes de abandonar (`beforeunload` e troca de rota) |

## Acessibilidade e responsividade

- Todos os controles alcançáveis por teclado, com foco visível; janelas modais com `role="dialog"`, `aria-modal` e foco preso.
- Gráficos têm `role="img"` e `aria-label`; a tabela é `<table>` real com `<th scope>`.
- `prefers-reduced-motion`: sem count-up, sem pulso, sem shimmer.
- Leitura (visão geral, lista, ficha) utilizável em celular sem rolagem horizontal da página; a tabela rola dentro do cartão
  (SC-008). KPIs 4 → 2 → 1 colunas.

## Segurança na interface

- Nenhum `innerHTML` com dado vindo da API sem escape; o front usa uma função única de escape e testes cobrem nomes com `<`, `"` e `&`.
- Nenhum segredo em `localStorage`, `sessionStorage` ou na URL; o estado de filtros e ordem fica no hash/consulta (sem dados pessoais).
- Sem script ou estilo inline (compatível com a CSP de `research.md` R-07); fontes e ícones locais.
- 401 em qualquer chamada leva ao login e, depois, de volta à tela de origem (caso de borda "sessão expirada").

## Testes de front (`node --test`, sem dependências)

Funções puras testadas fora do navegador: `validar.js` (slug, instância, segredo, horário, faixas, exatamente as regras do contrato),
`formatar.js` (números, moeda, "há X min", fuso), `atencao.js` (apresentação dos motivos), `graficos.js` (arcos do donut fecham 100%, larguras
do funil ≥ 20%, escala dos eixos) e `escape.js`.
