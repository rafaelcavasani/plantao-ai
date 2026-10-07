// Conversas da empresa só por metadados (US5, FR-005): sem texto de mensagem e sem contato, nem mascarado.

import { api, caminhos } from "../api.js";
import { bloco, naoEncontrada, vazio } from "../componentes/estados.js";
import { h, icone } from "../dom.js";
import { dataHora, hora, inteiro, pct, REMETENTE } from "../formatar.js";
import { hrefs } from "../rotas.js";

const STATUS = { aberta: "Aberta", handoff: "Aguardando pessoa", resolvida: "Resolvida" };
const AGENTE = { router: "Roteador", support: "Suporte", humano: "Atendente" };

const voltar = (href, texto) => h("div", { class: "row" }, h("a", { class: "back", href }, icone("arrow-left"), ` ${texto}`));
const aviso = () => h("p", { class: "ro-note aviso-privacidade" }, icone("shield-halved"),
  " O painel mostra só metadados. O texto das mensagens e o contato do cliente não ficam disponíveis aqui.");

export async function lista({ conteudo, shell, rota }) {
  const slug = rota.slug;
  shell.titulo("Conversas da ", "Empresa");
  shell.acoes();
  const corpo = h("div");
  conteudo.replaceChildren(h("div", { class: "dashboard" }, voltar(hrefs.ficha(slug), "Voltar para a ficha"), aviso(),
    h("article", { class: "card sem-animacao" }, h("div", { class: "card-head" }, h("h2", null, "Conversas recentes")), corpo)));
  let pagina = 1;
  const carregar = () => bloco(corpo,
    () => api.get(caminhos.conversas(slug), { pagina, tamanho: 20 }),
    (r) => {
      if (!r.itens.length) return vazio("Esta empresa ainda não tem conversas.");
      const paginas = Math.max(1, Math.ceil(r.total / r.tamanho));
      return h("div", null,
        h("div", { class: "table-scroll" }, h("table", null,
          h("thead", null, h("tr", null, ["Conversa", "Canal", "Status", "Agente", "Início", "Última atividade"].map((t) => h("th", { scope: "col" }, t)),
            h("th", { scope: "col", class: "r" }, "Mensagens"))),
          h("tbody", null, r.itens.map((c) => h("tr", null,
            h("td", { class: "name" }, h("a", { class: "link", href: hrefs.conversa(slug, c.id) }, c.id_curto)),
            h("td", null, c.canal), h("td", null, STATUS[c.status] ?? c.status), h("td", null, AGENTE[c.agente_atual] ?? c.agente_atual),
            h("td", null, dataHora(c.iniciada_em)), h("td", null, dataHora(c.ultima_atividade_em)),
            h("td", { class: "r num" }, inteiro(c.total_mensagens))))))),
        h("div", { class: "paginacao" },
          h("span", { class: "foot-note" }, `${inteiro(r.total)} conversa${r.total === 1 ? "" : "s"}`),
          paginas > 1 ? h("span", { class: "pag" },
            h("button", { class: "btn sm", type: "button", disabled: pagina <= 1, onclick: () => { pagina--; carregar(); } }, icone("chevron-left"), " Anterior"),
            h("span", { class: "foot-note" }, `Página ${pagina} de ${paginas}`),
            h("button", { class: "btn sm", type: "button", disabled: pagina >= paginas, onclick: () => { pagina++; carregar(); } }, "Próxima ", icone("chevron-right"))) : null));
    });
  await carregar();
  return { destruir() { shell.acoes(); } };
}

export async function detalhe({ conteudo, shell, rota }) {
  const { slug, id } = rota;
  shell.titulo("Conversa ", "(metadados)");
  shell.acoes();
  const corpo = h("div");
  conteudo.replaceChildren(h("div", { class: "dashboard" }, voltar(hrefs.conversas(slug), "Voltar para as conversas"), aviso(), corpo));
  try {
    const c = await api.get(caminhos.conversa(slug, id));
    corpo.replaceChildren(
      h("article", { class: "card sem-animacao" }, h("div", { class: "card-head" }, h("h2", null, `Conversa ${c.id_curto}`), h("small", null, c.id)),
        h("dl", { class: "kv" },
          h("div", null, h("dt", null, "Canal"), h("dd", null, c.canal)),
          h("div", null, h("dt", null, "Status"), h("dd", null, STATUS[c.status] ?? c.status)),
          h("div", null, h("dt", null, "Agente atual"), h("dd", null, AGENTE[c.agente_atual] ?? c.agente_atual)),
          h("div", null, h("dt", null, "Iniciada por"), h("dd", null, c.iniciada_por === "empresa" ? "a empresa" : "o contato")),
          h("div", null, h("dt", null, "Início"), h("dd", null, dataHora(c.iniciada_em))),
          h("div", null, h("dt", null, "Mensagens"), h("dd", null, inteiro(c.total_mensagens)))),
        c.handoff ? h("p", { class: "foot-note" }, icone("hand", "tone-warn"),
          ` Passou para uma pessoa em ${dataHora(c.handoff.em)}. Motivo: ${c.handoff.motivo}. Confiança no momento: ${pct(c.handoff.confianca * 100, 0)}.`) : null),
      h("article", { class: "card sem-animacao" }, h("div", { class: "card-head" }, h("h2", null, "Linha do tempo")),
        h("ul", { class: "audit" }, c.linha_do_tempo.map((m) => h("li", null,
          h("time", null, hora(m.em)), h("code", null, REMETENTE[m.remetente] ?? m.remetente),
          h("span", null, m.tipo === "nao_texto" ? "mensagem sem texto (áudio ou imagem)" : "mensagem de texto",
            m.intencao ? ` · intenção: ${m.intencao}${m.intencao_confianca ? ` (${pct(m.intencao_confianca * 100, 0)})` : ""}` : "",
            m.status_envio ? ` · envio: ${m.status_envio}` : ""))))));
  } catch (erro) {
    if (erro?.status === 404) corpo.replaceChildren(naoEncontrada("Conversa não encontrada.", hrefs.conversas(slug)));
    else if (erro?.status !== 401) corpo.replaceChildren(vazio(erro.mensagem));
  }
  return { destruir() { shell.acoes(); } };
}
