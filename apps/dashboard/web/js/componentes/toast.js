// Aviso curto de resultado (por exemplo, "Registrado na auditoria").

import { h } from "../dom.js";

export function avisar(texto, { duracaoMs = 4000 } = {}) {
  const el = h("div", { class: "toast", role: "status" }, texto);
  document.body.append(el);
  setTimeout(() => el.remove(), duracaoMs);
  return el;
}
