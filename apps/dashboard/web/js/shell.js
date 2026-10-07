// Estrutura fixa do painel: barra lateral vertical recolhível (toda a navegação mora nela) e barra superior com
// título e ações (nunca navegação). Contrato: specs/004-admin-dashboard/contracts/painel-ui.md.

import { api, caminhos } from "./api.js";
import { h, icone } from "./dom.js";
import { PERIODOS, relativo } from "./formatar.js";
import { lembrarMenu, menuRecolhidoSalvo } from "./estado.js";
import { avisar } from "./componentes/toast.js";

const ITENS = [
  { id: "visao-geral", href: "#/", icone: "chart-pie", rotulo: "Visão Geral" },
  { id: "empresas", href: "#/empresas", icone: "building", rotulo: "Empresas" },
];

const TELA_ATIVA = {
  "visao-geral": "visao-geral",
  empresas: "empresas",
  formulario: "empresas",
  ficha: "empresas",
  conversas: "empresas",
  conversa: "empresas",
};

/** Monta o shell dentro de `raiz` e devolve o que as telas precisam para se encaixar nele. */
export function montarShell(raiz, { operador, aoSair }) {
  const estreita = window.matchMedia("(max-width: 1199px)");
  const app = h("div", { class: "app" });
  const inicial = menuRecolhidoSalvo();
  if (inicial ?? estreita.matches) app.classList.add("collapsed");

  // --- Barra lateral ---
  const nav = h("nav", { class: "nav", "aria-label": "Principal" },
    ITENS.map((i) => h("a", { href: i.href, class: "nav-item", "data-id": i.id, "data-tip": i.rotulo },
      icone(i.icone), h("span", { class: "label" }, i.rotulo))));
  const recolher = h("button", { class: "collapse-btn", type: "button", "aria-label": "Recolher ou expandir o menu",
    onclick: () => { app.classList.toggle("collapsed"); lembrarMenu(app.classList.contains("collapsed")); } },
  icone("chevron-left"));
  const sair = h("button", { class: "collapse-btn sair", type: "button", title: "Sair", "aria-label": "Sair", onclick: aoSair },
    icone("right-from-bracket"));
  const nome = operador.email.split("@")[0];
  const lateral = h("aside", { class: "sidebar" },
    h("div", { class: "logo", "aria-label": "Plantão.AI" }, "P", h("span", { class: "rest" }, "lantão", h("span", { class: "grad" }, ".AI"))),
    recolher, nav,
    h("div", { class: "sidebar-foot" },
      h("div", { class: "avatar", "aria-hidden": "true" }, nome.slice(0, 2).toUpperCase()),
      h("div", { class: "who" }, h("b", null, nome), h("span", null, operador.papel === "operacao" ? "Operação" : "Leitura")),
      sair));
  const cortina = h("div", { class: "scrim", onclick: () => app.classList.remove("menu-open") });
  nav.addEventListener("click", () => app.classList.remove("menu-open"));

  // --- Barra superior ---
  const titulo = h("h1", { id: "titulo" });
  const atualizado = h("span", { class: "updated", role: "status" });
  const botaoAtualizar = h("button", { class: "ghost", type: "button" }, icone("rotate"), " Atualizar");
  const periodo = h("div", { class: "seg", role: "group", "aria-label": "Período" },
    Object.entries(PERIODOS).map(([valor, rotulo]) => h("button", { type: "button", "data-p": valor }, rotulo)));
  const exportar = h("button", { class: "ghost", type: "button" }, icone("download"), " Exportar");
  const menu = h("button", { class: "menu-btn", type: "button", "aria-label": "Abrir o menu", onclick: () => app.classList.add("menu-open") }, icone("bars"));
  const topo = h("header", { class: "topbar" },
    h("div", { class: "topbar-left" }, menu, titulo),
    h("div", { class: "topbar-right" }, atualizado, botaoAtualizar, periodo, exportar));
  const conteudo = h("div", { class: "conteudo", id: "conteudo" });
  const principal = h("main", { class: "content" }, topo, conteudo);

  app.append(lateral, cortina, principal);
  raiz.replaceChildren(app);

  // --- API para as telas ---
  let momento = null; // ISO da última atualização dos números
  const pintarAtualizado = () => {
    atualizado.textContent = momento ? `Atualizado ${relativo(momento)}` : "";
  };
  const relogio = setInterval(pintarAtualizado, 30000);

  const controle = {
    conteudo,
    aoMudarPeriodo: null,
    aoExportar: null,
    aoAtualizar: null,

    titulo(inicio, destaque) {
      titulo.replaceChildren(inicio, h("span", { class: "grad" }, destaque));
      document.title = `${inicio}${destaque} · Plantão.AI`;
    },

    /** Mostra só as ações que a tela usa. */
    acoes({ periodo: comPeriodo = false, exportar: comExportar = false, atualizar: comAtualizar = false } = {}) {
      periodo.hidden = !comPeriodo;
      exportar.hidden = !comExportar;
      botaoAtualizar.hidden = !comAtualizar;
      atualizado.hidden = !comAtualizar;
      controle.aoMudarPeriodo = null;
      controle.aoExportar = null;
      controle.aoAtualizar = null;
    },

    periodoAtual(valor) {
      periodo.querySelectorAll("button").forEach((b) => {
        const ativo = b.dataset.p === valor;
        b.classList.toggle("on", ativo);
        b.setAttribute("aria-pressed", String(ativo));
      });
    },

    atualizadoEm(iso) {
      momento = iso;
      pintarAtualizado();
    },

    ativo(tela) {
      const id = TELA_ATIVA[tela] ?? null;
      nav.querySelectorAll(".nav-item").forEach((a) => {
        const ativo = a.dataset.id === id;
        a.classList.toggle("active", ativo);
        if (ativo) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
    },

    destruir() {
      clearInterval(relogio);
    },
  };

  periodo.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-p]");
    if (b && controle.aoMudarPeriodo) controle.aoMudarPeriodo(b.dataset.p);
  });
  exportar.addEventListener("click", () => controle.aoExportar?.());

  // "Atualizar": pede a agregação, espera `atualizado_em` mudar (até 60 s) e então recarrega a tela.
  let bloqueado = false;
  botaoAtualizar.addEventListener("click", async () => {
    if (bloqueado || !controle.aoAtualizar) return;
    bloqueado = true;
    botaoAtualizar.disabled = true;
    botaoAtualizar.replaceChildren(icone("rotate", "girando"), " Atualizando...");
    try {
      const antes = (await api.post(caminhos.atualizar)).atualizado_em;
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const saude = await api.get(caminhos.saude).catch(() => null);
        if (saude && saude.atualizado_em !== antes) break;
      }
      await controle.aoAtualizar();
    } catch (erro) {
      if (erro?.status !== 401) avisar(erro?.mensagem ?? "Não foi possível atualizar agora.");
    } finally {
      botaoAtualizar.replaceChildren(icone("rotate"), " Atualizar");
      setTimeout(() => { bloqueado = false; botaoAtualizar.disabled = false; }, 30000);
    }
  });

  return controle;
}
