// Janela modal acessível: foco preso, Esc cancela, foco volta a quem abriu. Confirmações de ação irreversível
// podem exigir um campo igual a um texto exato (por exemplo, o nome da empresa para encerrar, FR-007).

import { h, icone } from "../dom.js";
import { ErroApi } from "../api.js";

/** Erro que a ação pode lançar para mostrar uma lista de itens dentro da janela (por exemplo, a prontidão). */
export class ErroModal extends Error {
  constructor(mensagem, itens = []) {
    super(mensagem);
    this.itens = itens; // [{ok: boolean, rotulo: string}]
  }
}

const FOCAVEIS = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Abre a janela e devolve `true` se a ação foi confirmada e concluída, `false` se foi cancelada.
 * `campos`: [{nome, rotulo, tipo: "texto" | "area", exato?: string, dica?: string}] — com `exato`, o botão
 * só habilita quando o valor digitado é IGUAL (maiúsculas e espaços contam).
 */
export function abrirModal({ titulo, texto, campos = [], rotuloConfirmar = "Confirmar", perigo = false, aoConfirmar }) {
  return new Promise((resolver) => {
    const anterior = document.activeElement;
    const controles = new Map();
    const erro = h("div", { class: "erro-modal", role: "alert", hidden: true });
    const confirmar = h("button", { class: `btn ${perigo ? "danger" : "primary"}`, type: "button" }, rotuloConfirmar);
    const cancelar = h("button", { class: "btn", type: "button" }, "Cancelar");

    const blocos = campos.map((c) => {
      const controle = c.tipo === "area"
        ? h("textarea", { id: `modal-${c.nome}`, rows: 3, maxlength: 500 })
        : h("input", { id: `modal-${c.nome}`, type: "text", autocomplete: "off", spellcheck: "false" });
      controles.set(c.nome, controle);
      return h("label", { class: "field" }, c.rotulo, controle, c.dica ? h("span", { class: "hint" }, c.dica) : null);
    });

    const valores = () => Object.fromEntries([...controles].map(([nome, el]) => [nome, el.value]));
    const exatosOk = () => campos.every((c) => c.exato === undefined || controles.get(c.nome).value === c.exato);
    const atualizar = () => { confirmar.disabled = !exatosOk(); };
    controles.forEach((el) => el.addEventListener("input", atualizar));
    atualizar();

    const painel = h("div", { class: "panel", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-titulo" },
      h("h3", { id: "modal-titulo" }, titulo),
      texto ? h("p", null, texto) : null,
      ...blocos,
      erro,
      h("div", { class: "row-btns" }, cancelar, confirmar));
    const camada = h("div", { class: "overlay" }, painel);

    const fechar = (resultado) => {
      document.removeEventListener("keydown", teclado, true);
      camada.remove();
      if (anterior instanceof HTMLElement) anterior.focus();
      resolver(resultado);
    };

    function teclado(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        fechar(false);
      } else if (e.key === "Tab") {
        const focaveis = [...painel.querySelectorAll(FOCAVEIS)];
        if (!focaveis.length) return;
        const primeiro = focaveis[0];
        const ultimo = focaveis[focaveis.length - 1];
        if (e.shiftKey && document.activeElement === primeiro) { e.preventDefault(); ultimo.focus(); }
        else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro.focus(); }
      }
    }

    cancelar.addEventListener("click", () => fechar(false));
    confirmar.addEventListener("click", async () => {
      confirmar.disabled = true;
      cancelar.disabled = true;
      erro.hidden = true;
      try {
        await aoConfirmar(valores());
        fechar(true);
      } catch (e) {
        const mensagem = e instanceof ErroModal || e instanceof ErroApi ? e.message : "Não foi possível concluir a ação.";
        erro.replaceChildren(
          h("p", null, icone("triangle-exclamation", "tone-crit"), ` ${mensagem}`),
          e instanceof ErroModal && e.itens.length
            ? h("ul", { class: "checks" }, e.itens.map((i) =>
              h("li", null, icone(i.ok ? "circle-check" : "circle-xmark", i.ok ? "tone-ok" : "tone-crit"), i.rotulo)))
            : null);
        erro.hidden = false;
        cancelar.disabled = false;
        atualizar();
      }
    });

    document.addEventListener("keydown", teclado, true);
    document.body.append(camada);
    (controles.values().next().value ?? cancelar).focus();
  });
}
