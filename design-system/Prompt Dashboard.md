# Dashboard de Marketing — Cadence Analytics

Você é um engenheiro frontend sênior com forte olho de design. Construa um **dashboard de analytics de marketing** em um único arquivo HTML (CSS e JS inline), dark mode, denso em dados mas respirável, seguindo À RISCA o design system abaixo. Nada de estética genérica de template — o resultado deve parecer um produto SaaS premium real.

---

## 1. DESIGN SYSTEM (obrigatório, não invente fora dele)

Usar o design system deste projeto

## 2. ESTRUTURA RAIZ (siga exatamente, este é o esqueleto do app)

body → div.app (display: flex, min-height: 100vh)
├── aside.sidebar (largura fixa 240px, height 100vh, position sticky top 0)
└── main.content (flex: 1, min-width: 0)
├── header.topbar
└── div.dashboard (grid de linhas com gap 16px, padding 32px)

**REGRA CRÍTICA DE LAYOUT:** TODOS os itens de navegação vivem DENTRO de `aside.sidebar`, empilhados verticalmente (flex-direction: column). É PROIBIDO renderizar qualquer item de nav no topo da página, na horizontal, ou fora da sidebar. A topbar contém APENAS título e ações — nunca navegação.

### Sidebar (fundo --bg-1, borda direita --border-s)
- Topo: logo — apenas o texto "Cadence" em Outfit, SEM ícone/mark ao lado
- Botão de collapse (chevron) logo abaixo do logo: alterna 240px (ícone + label) ↔ 64px (só ícones centralizados, tooltip no hover). Transição de largura 0.3s var(--ease-out); o main se ajusta naturalmente pelo flex. Colapsada, o logo vira só "C"
- Nav vertical: Visão Geral (ativo), Campanhas, Funil, Audiências, Criativos, Relatórios, Configurações — ícones **Font Awesome** (CDN oficial, `<i class="fa-solid fa-...">`: fa-chart-pie, fa-bullhorn, fa-filter, fa-users, fa-image, fa-file-lines, fa-gear) + label. Item ativo: fundo teal 8% + borda esquerda 2px --accent
- Rodapé da sidebar: avatar + nome do usuário + plano (só avatar quando colapsada)

### Topbar
- Esquerda: título "Visão Geral de <span gradiente>Marketing</span>"
- Direita, alinhados nesta ordem: texto "Atualizado há 2 min" (0.72rem, cor --muted, texto simples — SEM pill, SEM borda, SEM dot), seletor de período (pills 7d / 30d / 90d, ativo em teal), botão "Exportar" (ghost)

---

## 3. CONTEÚDO DO DASHBOARD (dentro de div.dashboard)

**Linha 1 — 4 KPI cards** (grid 4 colunas, gap 16px)
1. Investimento Total: R$ 84.320 · +12,4% vs período anterior
2. ROAS: 4.8x · +0.6x (verde)
3. CPA Médio: R$ 42,80 · −8,2% (verde, queda é boa)
4. CTR Médio: 2,34% · −0,3pts (âmbar)
Cada card: label muted em cima, valor grande Outfit, delta colorido com seta (Font Awesome), mini-sparkline SVG na base.

**Linha 2 — split 2fr / 1fr**
- Card grande: gráfico de linha "Investimento vs Receita" em SVG (2 séries: investimento em teal sólido, receita em teal claro tracejado), área com gradiente de preenchimento, eixo X com períodos, legenda com dots. No ÚLTIMO ponto de cada série, um `<circle>` com cx/cy FIXOS nas coordenadas exatas desse ponto, pulsando apenas via scale/opacity (transform-box: fill-box; transform-origin: center) — sem nenhuma animação de posição
- Card menor: donut "Distribuição por Canal" — Meta Ads 46%, Google 28%, TikTok 16%, E-mail 10%. **Matemática obrigatória do donut:** um `<circle>` por segmento sobre a mesma circunferência C = 2πr; cada segmento com `stroke-dasharray: (fração × C) C` e `stroke-dashoffset` acumulado igual a −(soma das frações anteriores × C); 4 cores distintas derivadas da paleta teal (accent-dark, accent, accent-light, #5EEAD4), casadas com os dots da legenda. A soma dos arcos visíveis deve fechar exatamente o círculo — valide mentalmente antes de escrever. Centro do donut: "Meta Ads · 46%" (canal líder), NUNCA "100%"

**Linha 3 — split 1fr / 1fr**
- Funil de conversão horizontal: Impressões 2.4M → Cliques 56K → Leads 8.2K → Vendas 1.9K. **Escala obrigatória:** larguras RELATIVAS por posição no funil, NÃO proporção linear dos valores absolutos (56K/2.4M daria uma barra de 2% — proibido). Use: Impressões 100%, Cliques 64%, Leads 42%, Vendas 24%, todas com transição de width na entrada. Mostrar valor absoluto à direita de cada barra e a % de conversão entre etapas (2,3% · 14,6% · 23,1%) como label pequeno entre as linhas. Barras com gradiente `90deg, --accent-dark → --accent-light` + shimmer sutil
- Feed de sinais ao vivo: linhas com dot de status pulsante no lugar (teal = oportunidade, âmbar = atenção, vermelho = crítico) + timestamp à direita. Ex.: "Campanha [BOF] Remarketing 7D — ROAS bateu 8.5x hoje", "Campanha [TOF] Display Branding — CPA subiu 18% em 24h", "Orçamento diário de [MOF] Lookalike quase esgotado". Ciclar mensagens via JS a cada ~3s

**Linha 4 — tabela de campanhas** (largura total)
Colunas: Campanha, Status (badge pill: Ativa/Pausada/Aprendizado), Investimento, Impressões, CTR, CPA, ROAS, barra de progresso de orçamento. 6–8 linhas com dados mockados realistas de Meta Ads (nomes tipo "[TOF] Vídeo Descoberta — Advantage+", "[BOF] Remarketing 7D"). ROAS colorido por faixa (≥4 verde, 2–4 âmbar, <2 vermelho). Hover na linha: fundo teal 4%.

---

## 4. COMPORTAMENTO

- Todos os dados mockados em JS (arrays/objetos), renderizados dinamicamente
- Count-up nos KPIs, desenho dos gráficos e stagger dos cards disparam no load
- Seletor de período troca os dados dos KPIs e do gráfico principal (2–3 datasets mockados) com transição suave — ao trocar, o dot do último ponto é REPOSICIONADO instantaneamente para as novas coordenadas (sem tween de trajeto) e continua só pulsando
- Sidebar collapse funcional com tooltips nos ícones quando colapsada
- Feed de sinais cicla mensagens; tabela ordenável ao clicar no header da coluna (bônus)
- Todos os ícones em **Font Awesome** via CDN (uma única biblioteca)
- Gráficos em SVG puro (sem libs de chart)

## 5. RESTRIÇÕES

- NÃO usar roxo/azul genérico de dashboard, NÃO usar sombras pretas duras, NÃO usar branco puro em fundos
- Nada de emoji na UI
- Responsivo: em <1200px a sidebar inicia colapsada; <768px vira menu hambúrguer sobreposto; KPIs 4→2→1 colunas
- Um único arquivo HTML, pronto pra abrir no browser

## 6. CHECKLIST FINAL (verifique antes de entregar)

- [ ] Nenhum item de nav fora da sidebar; nav 100% vertical dentro do aside
- [ ] Topbar presente com título + "Atualizado há 2 min" (texto puro, à direita) + período + Exportar
- [ ] Donut com 4 segmentos proporcionais que fecham o círculo; centro mostra o canal líder
- [ ] Barras do funil visíveis em escala relativa (nenhuma barra menor que 20% da largura)
- [ ] Dots pulsantes fixos no lugar — zero animação de posição/translate/cx/cy
