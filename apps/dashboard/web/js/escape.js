// Escape de texto para os raros pontos em que um valor precisa virar HTML ou atributo. O restante do painel
// monta DOM por `dom.js`, onde texto nunca é interpretado como HTML.

const MAPA = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapar(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, (c) => MAPA[c]);
}
