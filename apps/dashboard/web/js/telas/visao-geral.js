// Visão geral da operação: KPIs, mensagens no tempo, empresas por estado, funil, atenção e tabela (US1).

import { api, baixar, caminhos } from "../api.js";
import { ordenarPorGravidade, visual } from "../atencao.js";
import { avisoDesatualizado, carregando, erroBloco, vazio } from "../componentes/estados.js";
import { tabelaEmpresas } from "../componentes/tabela-empresas.js";
import { h, icone } from "../dom.js";
import { definir, obter } from "../estado.js";
import {
  COMPARACAO, ESTADOS, inteiro, pct, usd, variacaoPct, variacaoPontos,
} from "../formatar.js";
import { contar, donut, funil, linha, sparkline } from "../graficos.js";
import { hrefs } from "../rotas.js";

const CORES_DOS_ESTADOS = { ativo: "#0d9488", em_configuracao: "#14b8a6", suspenso: "#2dd4bf", encerrado: "#5eead4" };

function kpi({ rotulo, valor, formatar, variacao, tom, serie, apoio, atrasoMs, comparacao }) {
  const valorEl = h("span", { class: "val num" }, formatar(0));
  const delta = variacao
    ? h("span", { class: `delta tone-${tom}` }, icone(variacao.valor >= 0 ? "arrow-up" : "arrow-down"), variacao.texto, " ", h("em", null, comparacao))
    : h("span", { class: "delta" }, h("em", null, "sem período anterior para comparar"));
  const card = h("article", { class: "card kpi" }, h("span", { class: "lbl" }, rotulo), valorEl, delta,
    serie && serie.length > 1 ? sparkline(serie, tom) : null, apoio ? h("span", { class: "lbl apoio" }, apoio) : null);
  card.style.animationDelay = `${atrasoMs}ms`;
  contar(valorEl, 0, valor, formatar);
  return card;
}

function kpis(v, periodo) {
  const t = v.totais;
  const cmp = COMPARACAO[periodo];
  const pontos = v.serie;
  const taxas = pontos.map((p) => (p.conversas ? (p.handoffs / p.conversas) * 100 : 0));
  const dMsg = variacaoPct(t.mensagens.valor, t.mensagens.anterior);
  const dConv = variacaoPct(t.conversas.valor, t.conversas.anterior);
  const dHand = t.conversas.valor && t.conversas.anterior
    ? variacaoPontos(t.taxa_handoff_pct.valor, t.taxa_handoff_pct.anterior) : null;
  const dCusto = variacaoPct(t.custo_usd.valor, t.custo_usd.anterior);
  const margem = t.margem_usd.disponivel ? `Margem estimada ${usd(t.margem_usd.valor)}` : "Margem indisponível";
  const sobe = (d) => (d && d.valor >= 0 ? "ok" : d ? "warn" : "ok");
  return h("section", { class: "row kpis", "aria-label": "Indicadores do período" },
    kpi({ rotulo: "Mensagens", valor: t.mensagens.valor, formatar: inteiro, variacao: dMsg, tom: sobe(dMsg), comparacao: cmp, atrasoMs: 0,
      serie: pontos.map((p) => p.recebidas + p.agente) }),
    kpi({ rotulo: "Conversas", valor: t.conversas.valor, formatar: inteiro, variacao: dConv, tom: sobe(dConv), comparacao: cmp, atrasoMs: 80,
      serie: pontos.map((p) => p.conversas),
      apoio: `${inteiro(t.conversas.abertas)} abertas · ${inteiro(t.conversas.handoff)} aguardando pessoa` }),
    kpi({ rotulo: "Taxa de handoff", valor: t.taxa_handoff_pct.valor, formatar: (n) => pct(n), variacao: dHand,
      tom: dHand && dHand.valor > 0 ? "warn" : "ok", comparacao: cmp, atrasoMs: 160, serie: taxas }),
    kpi({ rotulo: "Custo (US$)", valor: t.custo_usd.valor, formatar: (n) => usd(n), variacao: dCusto,
      tom: dCusto && dCusto.valor > 0 ? "warn" : "ok", comparacao: cmp, atrasoMs: 240,
      serie: pontos.map((p) => p.custo_usd), apoio: margem }));
}

function cartaoLinha(v, animar) {
  const alvo = h("div", { class: "chart-wrap" });
  const rotulos = v.serie.map((p) => `${new Date(p.inicio).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo",
    ...(v.periodo === "hoje" ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "short" }) }).replace(".", "")}`);
  const card = h("article", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Mensagens no período"),
      h("div", { class: "legend" },
        h("span", null, h("i", { class: "dot cor-recebidas" }), "Recebidas"),
        h("span", null, h("i", { class: "dot cor-agente" }), "Respondidas pelo agente"))),
    alvo);
  linha(alvo, {
    rotulos,
    series: [
      { nome: "Recebidas", valores: v.serie.map((p) => p.recebidas), cor: "#14b8a6" },
      { nome: "Pelo agente", valores: v.serie.map((p) => p.agente), cor: "#5eead4", tracejada: true },
    ],
    formatarValor: inteiro, animar, idGrafico: "geral",
  });
  return card;
}

function cartaoEstados(v) {
  const estados = Object.keys(ESTADOS).map((e) => ({ chave: e, nome: ESTADOS[e], valor: v.empresas_por_estado[e], cor: CORES_DOS_ESTADOS[e] }));
  const lider = estados.reduce((a, b) => (b.valor > a.valor ? b : a));
  const num = h("b", null, inteiro(lider.valor));
  const rot = h("span", null, lider.nome);
  const alvo = h("div", { class: "donut" });
  const centro = h("div", { class: "donut-center" }, num, rot);
  const mostrar = (item) => { const i = item ?? lider; num.textContent = inteiro(i.valor); rot.textContent = i.nome; };
  const area = h("div", { class: "donut-svg-wrap" });
  alvo.append(area, centro);
  donut(area, estados, { aoPassar: mostrar });
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Empresas por estado"), h("small", null, `${inteiro(v.empresas_por_estado.total)} no total`)),
    h("div", { class: "donut-wrap" }, alvo,
      h("ul", { class: "dlegend" }, estados.map((e) =>
        h("li", null, h("i", { class: "dot", dataset: { cor: e.cor } }), e.nome, h("b", { class: "num" }, inteiro(e.valor)))))));
}

function cartaoFunil(v) {
  const f = v.funil;
  const alvo = h("div", { class: "funnel" });
  const razao = (a, b) => (b ? pct((a / b) * 100) : "—");
  funil(alvo,
    [
      { nome: "Conversas", texto: inteiro(f.conversas) },
      { nome: "Pelo agente", texto: inteiro(f.respondidas_agente) },
      { nome: "Handoff", texto: inteiro(f.handoff) },
      { nome: "Resolvidas", texto: inteiro(f.resolvidas_humano) },
    ],
    [
      `${razao(f.respondidas_agente, f.conversas)} respondidas pelo agente`,
      `${razao(f.handoff, f.conversas)} escalaram para uma pessoa`,
      `${razao(f.resolvidas_humano, f.handoff)} resolvidas pela pessoa`,
    ]);
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Funil de atendimento"), h("small", null, "Largura relativa por etapa")), alvo);
}

function cartaoAtencao(v) {
  const itens = ordenarPorGravidade(v.atencao);
  const lista = itens.length
    ? h("ul", { class: "feed" }, itens.map((a) => {
      const primeiro = visual(a.motivos[0]);
      return h("li", null,
        h("i", { class: `sdot ${a.gravidade === "critica" ? "crit" : "warn"}`, "aria-hidden": "true" }),
        h("span", { class: "msg" }, icone(primeiro.icone, "tone-warn"), " ",
          h("a", { class: "link", href: hrefs.ficha(a.slug) }, a.nome), ` — ${a.detalhe}`),
        h("time", null, a.gravidade === "critica" ? "crítico" : "atenção"));
    }))
    : vazio("Nenhuma empresa precisa de atenção agora.");
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Atenção ao vivo"),
      h("span", { class: "live" }, h("i", { class: "sdot ok", "aria-hidden": "true" }), "Monitorando")), lista);
}

export async function montar({ conteudo, shell }) {
  let primeira = true;
  const raiz = h("div", { class: "dashboard" });
  const topo = h("div", { class: "row" });
  const grade = h("div", { class: "dashboard-interna" });
  const cartaoTabela = h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Empresas"),
    h("small", null, "Clique no cabeçalho para ordenar")));
  const tabela = tabelaEmpresas({
    modo: "resumo",
    periodo: () => obter().periodo,
    aoCarregar: (r) => shell.atualizadoEm(r.atualizado_em),
  });
  cartaoTabela.append(tabela.elemento);
  raiz.append(topo, grade, h("section", { class: "row" }, cartaoTabela));
  conteudo.replaceChildren(raiz);

  shell.titulo("Visão geral da ", "Operação");
  shell.acoes({ periodo: true, exportar: true, atualizar: true });
  shell.periodoAtual(obter().periodo);

  async function recarregar() {
    const periodo = obter().periodo;
    shell.periodoAtual(periodo);
    topo.replaceChildren(carregando(2));
    grade.replaceChildren();
    let v;
    try {
      v = await api.get(caminhos.visaoGeral, { periodo });
    } catch (erro) {
      if (erro?.status !== 401) topo.replaceChildren(erroBloco(erro, recarregar));
      return;
    }
    shell.atualizadoEm(v.atualizado_em);
    topo.replaceChildren(kpis(v, periodo));
    const idade = v.atualizado_em ? (Date.now() - new Date(v.atualizado_em).getTime()) / 1000 : 0;
    if (idade > 600) topo.prepend(avisoDesatualizado());
    grade.replaceChildren(
      h("section", { class: "row r2" }, cartaoLinha(v, primeira), cartaoEstados(v)),
      h("section", { class: "row r3" }, cartaoFunil(v), cartaoAtencao(v)));
    grade.querySelectorAll(".dot[data-cor]").forEach((d) => { d.style.background = d.dataset.cor; });
    primeira = false;
    await tabela.carregar();
  }

  shell.aoMudarPeriodo = (p) => { definir({ periodo: p }); recarregar(); };
  shell.aoAtualizar = recarregar;
  shell.aoExportar = () => baixar(caminhos.empresasCsv, tabela.filtros(), "plantao-empresas.csv")
    .catch((e) => { if (e?.status !== 401) topo.append(erroBloco(e)); });
  await recarregar();
  return { destruir() { shell.acoes(); } };
}

