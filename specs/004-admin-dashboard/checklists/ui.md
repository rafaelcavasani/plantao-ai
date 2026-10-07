# Checklist de interface: acessibilidade e responsividade (T086)

**Feature**: [spec.md](../spec.md) | **Contrato**: [painel-ui.md](../contracts/painel-ui.md)

Tudo abaixo foi **verificado**: por cálculo, por teste automatizado ou em Chrome real (headless, via `playwright-core`,
com `axe-core`). O script que repete a verificação está em [`scripts/painel_e2e/`](../../../scripts/painel_e2e/LEIA-ME.md)
(`navegador-real.mjs`). Resultado da última execução: **todas as verificações passaram** nas 6 telas (visão geral, empresas,
ficha, nova empresa, editar, conversas), depois das correções listadas no fim.

## Contraste (FR-032, nível AA)

- [x] Texto principal `#e5e7eb` sobre `#050505`, `#0a0a0d`, `#0e0e12` e `#14141a`: de 14,8 a 16,5 (mínimo 4,5)
- [x] Texto secundário `#b4b4b4` e `#969aa0`: de 6,5 a 9,8
- [x] Cores de estado sobre os fundos escuros: teal 9,9 a 11, alerta 10,4 a 11,6, crítico 6,6 a 7,4, ok 10,5 a 11,7
- [x] Botão primário (`#031412` sobre `#0d9488`): 5,0; no hover: 7,6
- [x] `axe-core` com as regras WCAG 2.0/2.1 A e AA (inclui `color-contrast`): **0 violações** nas 6 telas
- [x] Cor nunca é o único sinal: badge de estado com texto, alerta com ícone e texto, variação com seta e valor, conexão com ícone e texto

## Teclado e foco

- [x] Toda ação é um `<a>`, `<button>`, `<input>`, `<select>` ou `<textarea>` nativo
- [x] Nenhum controle visível fora da ordem de `Tab` (medido no navegador)
- [x] Foco visível: contorno de 2 px nos itens de menu (medido no navegador)
- [x] Janela modal: `role="dialog"`, `aria-modal`, `aria-labelledby`; **8 voltas de `Tab` e 8 de `Shift+Tab` ficam presas dentro da janela**; `Esc` fecha; o foco volta ao botão que abriu (medido no navegador)
- [x] Erro de formulário leva o foco ao primeiro campo com erro

## Semântica e tecnologia assistiva

- [x] `axe-core` (regras de nome acessível, papéis ARIA, landmarks, listas, tabelas, formulários): 0 violações nas 6 telas
- [x] Tabelas são `<table>` com `<th scope="col">` e `aria-sort`; gráficos com `role="img"` e `aria-label`; ícones decorativos com `aria-hidden`
- [x] Erros de campo e de bloco usam `role="alert"`; avisos de estado usam `role="status"`
- [x] Texto alternativo do ícone de atenção (`title` e texto `sr` com o motivo)
- Observação: nenhuma ferramenta automática substitui ouvir a tela com NVDA ou VoiceOver. A verificação cobre o que um leitor de tela precisa (nomes, papéis, ordem, listas), mas a experiência falada em si não foi ouvida.

## Movimento

- [x] `prefers-reduced-motion` emulado no Chrome: pulso do último ponto em 0,01 ms, brilho do funil em 0,01 ms (incluindo `::after`), count-up desligado (o KPI já nasce com o valor final)
- [x] Marca do último ponto do gráfico: `cx`/`cy` fixos, sem atributo `style`, pulsa só em `scale` e `opacity`

## Responsividade (SC-008), medida no Chrome

- [x] Sem rolagem horizontal da página em **390, 768 e 1000 px** nas 6 telas (`scrollWidth <= innerWidth`)
- [x] KPIs em **4 colunas a 1366 px, 2 a 1000 e 768 px, 1 a 390 px**
- [x] Barra lateral de 240 px que recolhe para 64 px com tooltip no hover; no celular o menu fica fora da tela, abre pelo botão, fecha ao tocar na cortina e ao escolher um item
- [x] A tabela rola dentro do cartão no celular (a página não rola)
- [x] Formulário de cadastro e edição utilizáveis em 768 e 1000 px (sem overflow)
- [x] Prints conferidos a olho: visão geral (desktop e celular), ficha e nova empresa

## Segurança na interface

- [x] **Nenhuma violação de CSP** nas 6 telas (ouvindo `securitypolicyviolation` no Chrome) e console e rede sem erro nem aviso
- [x] Nenhum `innerHTML` nem atributo `style` no código do front (`dom.js` lança erro se alguém passar `style`)
- [x] Texto vindo da API entra sempre como nó de texto (`escape.test.js`)
- [x] Nenhum segredo em `localStorage`, `sessionStorage` ou URL
- [x] Fontes (Inter, Outfit) e Font Awesome carregam dos arquivos locais (`document.fonts.check`)

## Defeitos que a verificação em navegador real encontrou e foram corrigidos

| # | Defeito | Correção |
|---|---|---|
| 1 | Ficha: `<p>` dentro de `<ul>` (HTML inválido; `axe` regra `list`) em "Prontidão" e "Histórico de auditoria" vazios | itens vazios viraram `<li class="vazio">` |
| 2 | "Reduzir movimento" não desligava o brilho do funil (`::after` ignorado pelo seletor `*`) | regra de movimento reduzido passou a cobrir `*::before` e `*::after` |
| 3 | O texto "null" aparecia no rodapé de tabelas (o DOM converte `null` em texto em `replaceChildren`) | `trocar()` ignora `null`; teste do navegador falha se aparecer "null", "undefined", "NaN" ou "[object Object]" |
| 4 | Rótulos do eixo X colados ("02 de out05 de out") | o penúltimo rótulo some quando o último é forçado; teste mede sobreposição |
| 5 | Texto "Tokens (entrada / saída)" encostando em "Embedding" no cartão de custo | espaçamento e linha divisória |
| 6 | Placeholder do horário cortado ("ou fechac") | placeholder curto; a dica do grupo já explica "fechado" |
