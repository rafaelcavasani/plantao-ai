// Tabela de empresas, com busca, filtro por estado e nicho, ordenação e paginação feitas no servidor (FR-013/014).
// `modo = "resumo"` (visão geral): atividade e custo. `modo = "gestao"` (tela Empresas): cadastro e ações.

import { api, caminhos } from "../api.js";
import { descricao, visual } from "../atencao.js";
import { nomesDosPlanos } from "../catalogo.js";
import { h, icone, trocar } from "../dom.js";
import { CLASSE_DO_ESTADO, ESTADOS, data, decimal, inteiro, pct, ultimaMensagem, usd } from "../formatar.js";
import { hrefs } from "../rotas.js";
import { carregando, erroBloco, vazio } from "./estados.js";

const COLUNAS = {
  resumo: [
    { rotulo: "Empresa", ordem: "nome" },
    { rotulo: "Estado", ordem: "estado" },
    { rotulo: "Mensagens", ordem: "mensagens", numerica: true },
    { rotulo: "Abertas", ordem: "abertas", numerica: true },
    { rotulo: "Handoffs", ordem: "handoffs", numerica: true },
    { rotulo: "Última mensagem", ordem: "ultima_mensagem" },
    { rotulo: "Custo (US$)", ordem: "custo", numerica: true },
    { rotulo: "Orçamento", ordem: "orcamento" },
  ],
  gestao: [
    { rotulo: "Empresa", ordem: "nome" },
    { rotulo: "Nicho" },
    { rotulo: "Plano" },
    { rotulo: "Estado", ordem: "estado" },
    { rotulo: "Conexão" },
    { rotulo: "Documentos", numerica: true },
    { rotulo: "Criada em", ordem: "criada_em" },
    { rotulo: "Ações", numerica: true },
  ],
};

const FILTROS_DE_ESTADO = [
  ["", "Todas"],
  ["ativo", "Ativas"],
  ["em_configuracao", "Em configuração"],
  ["suspenso", "Suspensas"],
  ["encerrado", "Encerradas"],
];

const CONEXAO = {
  verificada: ["circle-check", "tone-ok", "Verificada"],
  nao_verificada: ["triangle-exclamation", "tone-warn", "Não verificada"],
  sem_conexao: ["link-slash", "tone-crit", "Sem conexão"],
};

function celulaNome(item) {
  const alertas = item.atencao.map((a) =>
    h("i", { class: `fa-solid fa-${visual(a.codigo).icone} flag tone-warn`, title: a.detalhe, "aria-hidden": "true" }));
  const lista = item.atencao.length ? h("span", { class: "sr" }, ` Atenção: ${descricao(item.atencao)}.`) : null;
  return h("td", { class: "name" },
    h("a", { class: "link", href: hrefs.ficha(item.slug) }, item.nome), alertas, lista,
    h("span", { class: "sub" }, item.slug));
}

function celulaOrcamento(item) {
  if (item.orcamento_pct === null) return h("td", null, h("span", { class: "sub" }, "sem orçamento"));
  const quente = item.orcamento_pct >= 90;
  const barra = h("div", { class: `f${quente ? " hot" : ""}` });
  barra.style.width = `${Math.min(100, item.orcamento_pct)}%`;
  return h("td", null, h("div", { class: "pbar" }, h("div", { class: "t" }, barra), h("span", { class: "num" }, pct(item.orcamento_pct, 0))));
}

function linhaResumo(item) {
  const ultima = ultimaMensagem(item.ultima_mensagem);
  return h("tr", null,
    celulaNome(item),
    h("td", null, h("span", { class: `badge ${CLASSE_DO_ESTADO[item.estado]}` }, ESTADOS[item.estado])),
    h("td", { class: "r num" }, inteiro(item.mensagens)),
    h("td", { class: "r num" }, inteiro(item.conversas_abertas)),
    h("td", { class: "r num" }, inteiro(item.handoffs)),
    h("td", null, ultima.quando, ultima.quem ? h("span", { class: "sub" }, ultima.quem) : null),
    h("td", { class: "r num" }, decimal(item.custo_usd, 2)),
    celulaOrcamento(item));
}

function linhaGestao(item, { podeEditar, nomes }) {
  const [ic, tom, texto] = CONEXAO[item.conexao];
  const editavel = podeEditar && item.estado !== "encerrado";
  return h("tr", null,
    celulaNome(item),
    h("td", null, item.nicho),
    h("td", null, nomes[item.plano] ?? item.plano),
    h("td", null, h("span", { class: `badge ${CLASSE_DO_ESTADO[item.estado]}` }, ESTADOS[item.estado])),
    h("td", null, h("span", { class: tom }, icone(ic), ` ${texto}`)),
    h("td", { class: "r num" }, inteiro(item.documentos)),
    h("td", null, data(item.criada_em)),
    h("td", { class: "r" },
      h("a", { class: "btn sm", href: hrefs.ficha(item.slug) }, "Ver"), " ",
      editavel ? h("a", { class: "btn sm", href: hrefs.editar(item.slug) }, icone("pen"), " Editar") : null));
}

/**
 * Cria a tabela e devolve `{elemento, carregar, filtros}`.
 * `periodo` é uma função (o período muda na barra superior); `aoCarregar(resposta)` recebe `atualizado_em`.
 */
export function tabelaEmpresas({ modo, periodo, podeEditar = false, aoCarregar = null, tamanho = 25 }) {
  const f = { q: "", estado: "", nicho: "", ordem: modo === "resumo" ? "mensagens" : "nome", sentido: modo === "resumo" ? "desc" : "asc", pagina: 1 };
  let nichos = [];
  let pedido = 0;

  const busca = h("input", { id: `busca-${modo}`, type: "search", placeholder: "Buscar por nome ou slug", "aria-label": "Buscar empresa" });
  let digitando = 0;
  busca.addEventListener("input", () => {
    clearTimeout(digitando);
    digitando = setTimeout(() => { f.q = busca.value; f.pagina = 1; carregar(); }, 250);
  });
  const filtroEstado = h("div", { class: "seg", role: "group", "aria-label": "Filtrar por estado" },
    FILTROS_DE_ESTADO.map(([valor, rotulo]) =>
      h("button", { type: "button", "data-s": valor, class: valor === "" ? "on" : "", "aria-pressed": valor === "" ? "true" : "false",
        onclick: (e) => {
          f.estado = valor; f.pagina = 1;
          filtroEstado.querySelectorAll("button").forEach((b) => { const on = b === e.currentTarget; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
          carregar();
        } }, rotulo)));
  const filtroNicho = h("select", { "aria-label": "Filtrar por nicho", onchange: (e) => { f.nicho = e.target.value; f.pagina = 1; carregar(); } },
    h("option", { value: "" }, "Todos os nichos"));
  const barra = h("div", { class: "toolbar" },
    h("label", { class: "search" }, icone("magnifying-glass"), busca), filtroEstado, filtroNicho);

  const corpo = h("tbody");
  const cabecalho = h("tr");
  const rodape = h("div", { class: "paginacao" });
  const estado = h("div", { class: "estado-da-tabela" });
  const tabela = h("table", null, h("thead", null, cabecalho), corpo);
  const elemento = h("div", null, barra, h("div", { class: "table-scroll" }, tabela), estado, rodape);

  function desenharCabecalho() {
    cabecalho.replaceChildren(...COLUNAS[modo].map((c) => {
      const ordenada = c.ordem && f.ordem === c.ordem;
      const th = h("th", { scope: "col", class: [c.numerica ? "r" : "", ordenada ? "sorted" : "", c.ordem ? "ordenavel" : ""].join(" ").trim(),
        "aria-sort": ordenada ? (f.sentido === "asc" ? "ascending" : "descending") : null },
      c.ordem
        ? h("button", { type: "button", class: "ordenar", onclick: () => {
          f.sentido = f.ordem === c.ordem && f.sentido === "asc" ? "desc" : f.ordem === c.ordem ? "asc" : (c.numerica || c.ordem === "ultima_mensagem" || c.ordem === "criada_em" ? "desc" : "asc");
          f.ordem = c.ordem; f.pagina = 1; carregar();
        } }, c.rotulo, icone(ordenada ? (f.sentido === "asc" ? "arrow-up" : "arrow-down") : "sort"))
        : c.rotulo);
      return th;
    }));
  }

  function paginacao(resposta) {
    const total = Math.max(1, Math.ceil(resposta.total / resposta.tamanho));
    trocar(rodape, 
      h("span", { class: "foot-note" }, `${inteiro(resposta.total)} empresa${resposta.total === 1 ? "" : "s"}`),
      total > 1
        ? h("span", { class: "pag" },
          h("button", { class: "btn sm", type: "button", disabled: f.pagina <= 1, onclick: () => { f.pagina--; carregar(); } }, icone("chevron-left"), " Anterior"),
          h("span", { class: "foot-note" }, `Página ${f.pagina} de ${total}`),
          h("button", { class: "btn sm", type: "button", disabled: f.pagina >= total, onclick: () => { f.pagina++; carregar(); } }, "Próxima ", icone("chevron-right")))
        : null);
  }

  async function carregar() {
    const meu = ++pedido;
    desenharCabecalho();
    estado.replaceChildren(carregando(2));
    try {
      const [resposta, nomes] = await Promise.all([
        api.get(caminhos.empresas, { ...f, periodo: periodo(), tamanho }),
        modo === "gestao" ? nomesDosPlanos() : Promise.resolve({}),
      ]);
      if (meu !== pedido) return; // uma busca mais nova já saiu
      if (!nichos.length && !f.q && !f.estado && !f.nicho) {
        nichos = [...new Set(resposta.itens.map((i) => i.nicho))].sort((a, b) => a.localeCompare(b, "pt-BR"));
        filtroNicho.replaceChildren(h("option", { value: "" }, "Todos os nichos"), ...nichos.map((n) => h("option", { value: n }, n)));
      }
      corpo.replaceChildren(...resposta.itens.map((i) => (modo === "resumo" ? linhaResumo(i) : linhaGestao(i, { podeEditar, nomes }))));
      estado.replaceChildren(resposta.itens.length ? "" : vazio("Nenhuma empresa encontrada."));
      paginacao(resposta);
      aoCarregar?.(resposta);
    } catch (erro) {
      if (meu !== pedido || erro?.status === 401) return;
      corpo.replaceChildren();
      estado.replaceChildren(erroBloco(erro, carregar));
    }
  }

  return { elemento, carregar, filtros: () => ({ ...f, periodo: periodo() }) };
}
