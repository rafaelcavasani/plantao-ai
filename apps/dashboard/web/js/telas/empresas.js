// Tela "Empresas": lista de gestão com busca, filtros e acesso à ficha e à edição (US4, FR-024).

import { baixar, caminhos } from "../api.js";
import { erroBloco } from "../componentes/estados.js";
import { tabelaEmpresas } from "../componentes/tabela-empresas.js";
import { h, icone } from "../dom.js";
import { obter, podeOperar } from "../estado.js";
import { hrefs } from "../rotas.js";

export async function montar({ conteudo, shell }) {
  shell.titulo("Gestão de ", "Empresas");
  shell.acoes({ exportar: true });

  const resumo = h("span", { id: "total-empresas" });
  const novo = podeOperar()
    ? h("a", { class: "btn primary", href: hrefs.nova }, icone("plus"), " Nova empresa")
    : h("span", { class: "ro-note" }, icone("eye"), " Papel de leitura: cadastro indisponível.");
  const tabela = tabelaEmpresas({
    modo: "gestao",
    periodo: () => obter().periodo,
    podeEditar: podeOperar(),
    aoCarregar: (r) => { resumo.textContent = `${r.total} empresa${r.total === 1 ? "" : "s"}`; shell.atualizadoEm(null); },
  });
  const erro = h("div");
  conteudo.replaceChildren(h("div", { class: "dashboard" },
    h("div", { class: "row" }, h("div", { class: "f-head" },
      h("div", null, h("h2", null, "Empresas"), h("div", { class: "meta" }, resumo)), novo)),
    erro,
    h("div", { class: "row" }, h("article", { class: "card sem-animacao" }, tabela.elemento))));

  shell.aoExportar = () => baixar(caminhos.empresasCsv, tabela.filtros(), "plantao-empresas.csv")
    .catch((e) => { if (e?.status !== 401) erro.replaceChildren(erroBloco(e)); });
  await tabela.carregar();
  return { destruir() { shell.acoes(); } };
}
