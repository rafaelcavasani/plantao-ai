// Campos de formulário com rótulo, dica e mensagem de erro no próprio campo (FR-035).

import { h } from "../dom.js";

/** `<label>` com o controle dentro: o texto do rótulo nomeia o controle para leitores de tela. */
export function campo({ chave, rotulo, controle, dica = null, largo = false }) {
  return h("label", { class: `field${largo ? " wide" : ""}`, dataset: { campo: chave } },
    rotulo, controle, dica ? h("span", { class: "hint" }, dica) : null, h("span", { class: "err", role: "alert" }));
}

/** Grupo de controles (por exemplo, os sete dias do horário) com uma mensagem de erro só. */
export function grupo({ chave, rotulo, filhos, dica = null }) {
  return h("div", { class: "field wide", role: "group", "aria-label": rotulo, dataset: { campo: chave } },
    h("span", { class: "rotulo-do-grupo" }, rotulo), ...filhos, dica ? h("span", { class: "hint" }, dica) : null,
    h("span", { class: "err", role: "alert" }));
}

/** Marca os campos com erro (`{chave: mensagem}`), limpa os outros e devolve o primeiro controle com erro. */
export function mostrarErros(raiz, erros, ordem = []) {
  let primeiro = null;
  const chaves = [...ordem, ...Object.keys(erros)];
  raiz.querySelectorAll("[data-campo]").forEach((el) => {
    const msg = erros[el.dataset.campo];
    el.classList.toggle("invalid", Boolean(msg));
    const alvo = el.querySelector(":scope > .err");
    if (alvo) alvo.textContent = msg ?? "";
    const controle = el.querySelector("input, textarea, select");
    if (controle) controle.setAttribute("aria-invalid", msg ? "true" : "false");
  });
  for (const chave of chaves) {
    if (!(chave in erros)) continue;
    const el = raiz.querySelector(`[data-campo="${CSS.escape(chave)}"]`);
    if (el) {
      primeiro = el.querySelector("input, textarea, select") ?? el;
      break;
    }
  }
  return primeiro;
}
