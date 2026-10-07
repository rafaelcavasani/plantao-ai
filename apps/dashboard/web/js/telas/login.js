// Tela de login: o acesso é pelo provedor de identidade (OIDC, ADR-0007). Não há senha no painel.

import { api, caminhos } from "../api.js";
import { h, icone } from "../dom.js";

/** `motivo`: "expirada" (sessão caiu no meio do uso) ou "negado" (e-mail fora da lista). */
export function telaDeLogin(raiz, { motivo = null } = {}) {
  const destino = `/painel/${window.location.hash}`;
  const entrar = `${caminhos.entrar}?destino=${encodeURIComponent(destino)}`;
  const aviso = {
    expirada: "Sua sessão terminou. Entre de novo para continuar de onde parou.",
    negado: "Este e-mail não tem acesso ao painel. Fale com quem administra a plataforma.",
  }[motivo];
  const botao = h("a", { class: "btn primary entrar", href: entrar }, icone("right-to-bracket"), " Entrar");
  const situacao = h("p", { class: "aviso-desatualizado", role: "alert", hidden: true });
  // Se o login não está configurado, avisa aqui em vez de mandar a pessoa para uma resposta de erro da API.
  api.get(`${caminhos.entrar.replace("/entrar", "/modo")}`).then((m) => {
    if (m.configurado) return;
    botao.setAttribute("aria-disabled", "true");
    botao.removeAttribute("href");
    situacao.replaceChildren(icone("triangle-exclamation", "tone-warn"), ` ${m.mensagem}`);
    situacao.hidden = false;
  }).catch(() => {});
  raiz.replaceChildren(
    h("div", { class: "overlay entrada" },
      h("div", { class: "panel" },
        h("div", { class: "logo semmargem" }, "Plantão", h("span", { class: "grad" }, ".AI")),
        h("h3", null, "Painel de operação"),
        h("p", null, "Entre com a sua conta para ver e gerenciar as empresas."),
        aviso ? h("p", { class: "aviso-desatualizado", role: "alert" }, icone("circle-info"), ` ${aviso}`) : null,
        situacao,
        botao)),
  );
}
