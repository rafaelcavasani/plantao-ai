// Ponto de entrada do painel: confere a sessão, monta o shell e liga as rotas (hash) às telas.
// Sessão expirada em qualquer chamada volta ao login e, depois de entrar, à tela de origem (caso de borda da spec).

import { api, caminhos } from "./api.js";
import { carregando, naoEncontrada } from "./componentes/estados.js";
import { definir } from "./estado.js";
import { resolverRota } from "./rotas.js";
import { montarShell } from "./shell.js";
import * as empresas from "./telas/empresas.js";
import * as conversas from "./telas/conversas.js";
import * as ficha from "./telas/ficha.js";
import * as formulario from "./telas/formulario.js";
import { telaDeLogin } from "./telas/login.js";
import * as visaoGeral from "./telas/visao-geral.js";
import { h } from "./dom.js";

const TELAS = {
  "visao-geral": visaoGeral.montar,
  empresas: empresas.montar,
  formulario: formulario.montar,
  ficha: ficha.montar,
  conversas: conversas.lista,
  conversa: conversas.detalhe,
  "nao-encontrada": async ({ conteudo }) => {
    conteudo.replaceChildren(h("div", { class: "dashboard" }, naoEncontrada("Página não encontrada.", "#/")));
    return { destruir() {} };
  },
};

export async function iniciar(raiz = document.getElementById("raiz")) {
  let shell = null;
  let tela = null;
  let hashAtual = window.location.hash;
  let restaurando = false;
  let sessaoAcabou = false;

  const parar = () => {
    tela?.destruir?.();
    tela = null;
  };

  async function renderizar() {
    if (!shell) return;
    parar();
    const rota = resolverRota(window.location.hash);
    shell.ativo(rota.tela);
    shell.conteudo.replaceChildren(carregando(4));
    window.scrollTo?.(0, 0);
    try {
      tela = await TELAS[rota.tela]({ conteudo: shell.conteudo, shell, rota });
    } catch (erro) {
      if (erro?.status !== 401) throw erro;
    }
  }

  function aoMudarHash() {
    if (restaurando) { restaurando = false; return; }
    if (tela?.podeSair && !tela.podeSair()) {
      restaurando = true;
      window.location.hash = hashAtual; // desfaz a navegação: o operador escolheu ficar na edição
      return;
    }
    hashAtual = window.location.hash;
    renderizar();
  }

  function mostrarLogin(motivo) {
    sessaoAcabou = true;
    parar();
    shell?.destruir();
    shell = null;
    telaDeLogin(raiz, { motivo });
  }

  async function sair() {
    try {
      await api.post(caminhos.sair);
    } catch {
      /* sai da tela mesmo assim */
    }
    definir({ operador: null });
    mostrarLogin(null);
  }

  window.addEventListener("sessao-expirada", () => { if (!sessaoAcabou) mostrarLogin("expirada"); });

  try {
    const operador = await api.get(caminhos.eu);
    definir({ operador });
    shell = montarShell(raiz, { operador, aoSair: sair });
  } catch (erro) {
    if (erro?.status === 401) mostrarLogin(null);
    else raiz.replaceChildren(h("p", { class: "vazio", role: "alert" }, erro?.mensagem ?? "Não foi possível abrir o painel."));
    return;
  }
  window.addEventListener("hashchange", aoMudarHash);
  await renderizar();
}

if (typeof document !== "undefined" && document.getElementById("raiz")) {
  iniciar();
}
