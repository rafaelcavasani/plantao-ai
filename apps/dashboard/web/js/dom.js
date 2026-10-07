// Construção de DOM sem innerHTML: todo texto entra como nó de texto, então dado vindo da API nunca vira HTML.
// Sem atributo `style` (a CSP do painel proíbe estilo inline): use classes, ou `estilo` (CSSOM) para valores
// calculados, como a largura de uma barra.

const NS_SVG = "http://www.w3.org/2000/svg";

function aplicar(el, props) {
  for (const [chave, valor] of Object.entries(props ?? {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (chave === "style") throw new Error("Atributo style é proibido pela CSP; use classes ou `estilo`.");
    if (chave === "class") el.setAttribute("class", String(valor));
    else if (chave === "texto") el.textContent = String(valor);
    else if (chave === "dataset") Object.assign(el.dataset, valor);
    else if (chave === "estilo") Object.assign(el.style, valor);
    else if (chave.startsWith("on") && typeof valor === "function") el.addEventListener(chave.slice(2), valor);
    else if (valor === true) el.setAttribute(chave, "");
    else el.setAttribute(chave, String(valor));
  }
}

function anexar(el, filhos) {
  for (const filho of filhos.flat(Infinity)) {
    if (filho === null || filho === undefined || filho === false) continue;
    el.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
}

/** Elemento HTML. `h("div", {class: "card"}, "texto", outroNo)`. */
export function h(tag, props, ...filhos) {
  const el = document.createElement(tag);
  aplicar(el, props);
  anexar(el, filhos);
  return el;
}

/** Elemento SVG. */
export function s(tag, props, ...filhos) {
  const el = document.createElementNS(NS_SVG, tag);
  aplicar(el, props);
  anexar(el, filhos);
  return el;
}

/** Ícone Font Awesome (decorativo: o texto vizinho carrega o significado). */
export function icone(nome, classe = "") {
  return h("i", { class: `fa-solid fa-${nome} ${classe}`.trim(), "aria-hidden": "true" });
}

/** Troca o conteúdo de `el` pelos `filhos`. */
export function trocar(el, ...filhos) {
  el.replaceChildren();
  anexar(el, filhos);
  return el;
}

export function emitir(nome, detalhe) {
  window.dispatchEvent(new CustomEvent(nome, { detail: detalhe }));
}
