// Estados obrigatórios de todo bloco (FR-027): carregando, vazio, erro, desatualizado e sem permissão.

import { h, icone } from "../dom.js";

/** Esqueleto no formato do bloco: nunca tela em branco. */
export function carregando(linhas = 3) {
  return h("div", { class: "esqueleto", "aria-busy": "true", "aria-label": "Carregando" },
    Array.from({ length: linhas }, (_, i) => h("div", { class: `esqueleto-linha l${(i % 3) + 1}` })));
}

export function vazio(texto, ...extra) {
  return h("p", { class: "empty vazio" }, texto, ...extra);
}

/** Erro só do bloco, com "Tentar de novo": os outros blocos seguem visíveis. */
export function erroBloco(erro, aoTentar) {
  return h("div", { class: "erro-bloco", role: "alert" },
    h("p", null, icone("triangle-exclamation", "tone-warn"), ` ${erro?.mensagem ?? "Não foi possível carregar este bloco."}`),
    aoTentar ? h("button", { class: "btn sm", type: "button", onclick: aoTentar }, icone("rotate-right"), " Tentar de novo") : null);
}

export function avisoDesatualizado() {
  return h("p", { class: "aviso-desatualizado", role: "status" },
    icone("clock", "tone-warn"), " Os números estão desatualizados (mais de 10 minutos sem atualização). Use Atualizar.");
}

export function semPermissao(texto = "O papel de leitura não permite esta ação.") {
  return h("div", { class: "card sem-animacao" }, h("p", { class: "empty vazio" }, icone("lock"), ` ${texto}`));
}

export function naoEncontrada(texto = "Empresa não encontrada.", href = "#/empresas") {
  return h("div", { class: "card sem-animacao" },
    h("p", { class: "empty vazio" }, texto),
    h("p", { class: "vazio" }, h("a", { class: "back", href }, icone("arrow-left"), " Voltar para a lista")));
}

/** Carrega um bloco com os três estados. `buscar` devolve os dados; `desenhar` recebe os dados e devolve o DOM. */
export async function bloco(alvo, buscar, desenhar) {
  alvo.replaceChildren(carregando());
  try {
    const dados = await buscar();
    alvo.replaceChildren(desenhar(dados));
    return dados;
  } catch (erro) {
    if (erro?.status === 401) return null; // o login assume
    alvo.replaceChildren(erroBloco(erro, () => bloco(alvo, buscar, desenhar)));
    return null;
  }
}
