// Ficha da empresa: identificação, conexão, prontidão, atendimento, custo, gráfico e auditoria (US2),
// com as ações de estado (US3) e o apagamento de dados da empresa encerrada (US4, P3).

import { api, caminhos, ErroApi } from "../api.js";
import { visual } from "../atencao.js";
import { bloco, carregando, naoEncontrada, vazio } from "../componentes/estados.js";
import { abrirModal, ErroModal } from "../componentes/modal.js";
import { avisar } from "../componentes/toast.js";
import { nomesDosPlanos } from "../catalogo.js";
import { h, icone, trocar } from "../dom.js";
import { definir, obter, podeOperar } from "../estado.js";
import {
  CLASSE_DO_ESTADO, ESTADOS, SEM_DADO, data, dataHora, decimal, inteiro, pct, usd,
} from "../formatar.js";
import { linha } from "../graficos.js";
import { hrefs } from "../rotas.js";

// `prontidao_reprovada` devolve o nome interno do item; aqui ele vira o texto da tela.
const ROTULO_DO_ITEM = {
  "configuracao completa": "Configuração mínima preenchida",
  "documentos indexados": "Documentos da base de conhecimento enviados",
  "conexao verificada": "Conexão do canal verificada",
  "conversa de teste": "Conversa de teste aprovada",
};

const kv = (rotulo, valor) => h("div", null, h("dt", null, rotulo), h("dd", null, valor));
const cartao = (titulo, apoio, ...filhos) =>
  h("article", { class: "card sem-animacao" }, h("div", { class: "card-head" }, h("h2", null, titulo), apoio ? h("small", null, apoio) : null), ...filhos);

function identificacao(f, nomes) {
  const e = f.empresa;
  const c = f.conexao;
  return cartao("Identificação e conexão", null, h("dl", { class: "kv" },
    kv("Criada em", data(e.criada_em)),
    kv("Ativada em", data(e.ativada_em)),
    kv("Canal", c ? "WhatsApp / Evolution" : "não cadastrado"),
    kv("Instância", c?.instancia ?? SEM_DADO),
    kv("Verificada em", c ? dataHora(c.verificada_em) : SEM_DADO),
    kv("Credenciais", c ? "configuradas" : "pendentes"),
    kv("Documentos / trechos", f.base ? `${inteiro(f.base.documentos)} / ${inteiro(f.base.trechos)}` : SEM_DADO),
    kv("Plano", nomes[e.plano] ?? e.plano)));
}

function prontidao(f, aoVerificar) {
  const p = f.prontidao;
  const itens = p
    ? p.itens.map((i) => h("li", null, icone(i.ok ? "circle-check" : "circle-xmark", i.ok ? "tone-ok" : "tone-crit"), i.rotulo))
    : [h("li", { class: "vazio" }, "Ainda não verificada.")];
  const acao = podeOperar() && f.empresa.estado !== "encerrado"
    ? h("button", { class: "btn sm", type: "button", onclick: aoVerificar }, icone("clipboard-check"), " Verificar prontidão") : null;
  return cartao("Prontidão", p ? (p.aprovada ? "aprovada" : "reprovada") : null,
    h("ul", { class: "checks" }, itens),
    p ? h("p", { class: "foot-note" }, `Verificada em ${dataHora(p.executada_em)} por ${p.operador}.`) : null,
    f.ultimo_teste ? h("p", { class: "foot-note" }, `Último teste: ${f.ultimo_teste.aprovado ? "aprovado" : "reprovado"} em ${dataHora(f.ultimo_teste.executado_em)}.`) : null,
    acao);
}

function atendimento(f) {
  const a = f.atendimento;
  if (!a) return cartao("Atendimento", null, vazio(`Dados apagados em ${data(f.empresa.dados_apagados_em)}.`));
  const m = a.mensagens;
  const estat = (rotulo, valor, tom = "") => h("div", { class: "stat" }, h("span", null, rotulo), h("b", { class: `num ${tom}` }, valor));
  return cartao("Atendimento", `período: ${f.periodo}`,
    h("div", { class: "stats" },
      estat("Mensagens", inteiro(m.lead + m.agente + m.humano)),
      estat("Conversas", inteiro(a.conversas.abertas + a.conversas.handoff + a.conversas.resolvidas)),
      estat("Taxa de handoff", pct(a.taxa_handoff_pct), a.taxa_handoff_pct > 30 ? "tone-warn" : ""),
      estat("Resposta média / p95", a.resposta_media_s === null ? SEM_DADO : `${decimal(a.resposta_media_s, 1)} s / ${decimal(a.resposta_p95_s, 0)} s`),
      estat("Do contato / agente / atendente", `${inteiro(m.lead)} / ${inteiro(m.agente)} / ${inteiro(m.humano)}`),
      estat("Sem tratamento (áudio, imagem)", inteiro(m.nao_texto)),
      estat("Bloqueios de guardrail", inteiro(a.bloqueios_guardrail)),
      estat("Falhas de envio", inteiro(a.falhas_envio), a.falhas_envio > 0 ? "tone-warn" : "")),
    a.motivos_handoff.length
      ? h("div", { class: "motivos" }, h("h3", null, "Principais motivos de handoff"),
        h("ul", { class: "checks" }, a.motivos_handoff.map((x) => h("li", null, `${x.motivo} — ${inteiro(x.total)}`))))
      : null);
}

function custo(f) {
  const c = f.custo;
  if (!c) return cartao("Custo", null, vazio(`Dados apagados em ${data(f.empresa.dados_apagados_em)}.`));
  const total = c.total_usd || 0;
  const linhas = Object.entries(c.por_finalidade).map(([nome, valor]) => {
    const barra = h("div", { class: "f" });
    barra.style.width = `${total ? (valor / total) * 100 : 0}%`;
    return h("div", { class: "line" }, h("span", null, { roteador: "Roteador", suporte: "Suporte", embedding: "Embedding" }[nome] ?? nome),
      h("div", { class: "pbar" }, h("div", { class: "t" }, barra)), h("b", { class: "num" }, usd(valor)));
  });
  const modelos = Object.entries(c.por_modelo);
  return cartao("Custo por finalidade", usd(total),
    h("div", { class: "split" }, linhas),
    h("dl", { class: "kv" },
      kv("Tokens (entrada / saída)", `${inteiro(c.tokens_entrada)} / ${inteiro(c.tokens_saida)}`),
      kv("Custo por conversa", c.por_conversa_usd === null ? SEM_DADO : usd(c.por_conversa_usd, 4)),
      kv("Orçamento do mês", c.orcamento_pct === null ? "sem orçamento" : `${pct(c.orcamento_pct, 0)} de ${usd(c.orcamento_usd)}`),
      kv("Preço do plano", c.preco_plano_usd === null ? SEM_DADO : usd(c.preco_plano_usd)),
      kv("Margem estimada", c.margem_usd === null ? "margem indisponível" : usd(c.margem_usd))),
    modelos.length ? h("div", { class: "motivos" }, h("h3", null, "Por modelo"),
      h("ul", { class: "checks" }, modelos.map(([m, v]) => h("li", null, `${m} — ${usd(v, 4)}`)))) : null);
}

function auditoria(slug) {
  const lista = h("ul", { class: "audit" });
  const rodape = h("div", { class: "paginacao" });
  let pagina = 1;
  async function carregar() {
    try {
      const r = await api.get(caminhos.auditoria(slug), { pagina, tamanho: 10 });
      lista.replaceChildren(...(r.itens.length ? r.itens.map((a) => h("li", null,
        h("time", null, dataHora(a.criado_em)), h("code", null, a.entidade),
        h("span", null, `${a.campo}: ${formatarValor(a.valor_anterior)} → ${formatarValor(a.valor_novo)} `, h("em", { class: "mudo" }, `· ${a.operador}`))))
        : [h("li", { class: "vazio" }, "Sem alterações registradas.")]));
      const paginas = Math.max(1, Math.ceil(r.total / r.tamanho));
      trocar(rodape, 
        h("span", { class: "foot-note" }, `${inteiro(r.total)} registro${r.total === 1 ? "" : "s"}`),
        paginas > 1 ? h("span", { class: "pag" },
          h("button", { class: "btn sm", type: "button", disabled: pagina <= 1, onclick: () => { pagina--; carregar(); } }, icone("chevron-left"), " Mais recentes"),
          h("span", { class: "foot-note" }, `Página ${pagina} de ${paginas}`),
          h("button", { class: "btn sm", type: "button", disabled: pagina >= paginas, onclick: () => { pagina++; carregar(); } }, "Mais antigos ", icone("chevron-right"))) : null);
    } catch (erro) {
      if (erro?.status !== 401) lista.replaceChildren(h("li", { class: "vazio" }, erro.mensagem));
    }
  }
  carregar();
  return cartao("Histórico de auditoria", "credenciais nunca aparecem", lista, rodape);
}

function formatarValor(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v).slice(0, 80);
  return String(v).length > 80 ? `${String(v).slice(0, 80)}…` : String(v);
}

// --- Ações de estado ---------------------------------------------------------------------------

const ACOES = {
  suspenso: { titulo: (n) => `Suspender ${n}?`, texto: "A empresa deixa de ser atendida a partir da próxima mensagem.", motivo: true },
  encerrado: { titulo: (n) => `Encerrar ${n}?`, texto: "O encerramento é definitivo: o número fica reservado e a empresa não volta a ficar ativa.", motivo: true, nome: true, perigo: true },
  retomar: { titulo: (n) => `Retomar ${n}?`, texto: "A empresa volta a responder mensagens.", motivo: false },
  ativar: { titulo: (n) => `Ativar ${n}?`, texto: "A empresa passa a responder mensagens se a prontidão estiver aprovada.", motivo: false },
};

async function mudarEstado(f, acao, recarregar) {
  const e = f.empresa;
  const chave = acao.para === "ativo" ? (e.estado === "suspenso" ? "retomar" : "ativar") : acao.para;
  const cfg = ACOES[chave];
  const campos = [];
  if (cfg.motivo) campos.push({ nome: "motivo", rotulo: "Motivo (opcional, vai para a auditoria)", tipo: "area" });
  if (cfg.nome) campos.push({ nome: "confirmacao", rotulo: `Digite o nome exato da empresa: ${e.nome}`, tipo: "texto", exato: e.nome });
  const concluido = await abrirModal({
    titulo: cfg.titulo(e.nome), texto: cfg.texto, campos, perigo: cfg.perigo, rotuloConfirmar: acao.rotulo,
    aoConfirmar: async (v) => {
      try {
        await api.post(caminhos.estado(e.slug), { versao: e.versao, para: acao.para, motivo: v.motivo?.trim() || null, confirmacao: v.confirmacao ?? null });
      } catch (erro) {
        if (!(erro instanceof ErroApi)) throw erro;
        if (erro.codigo === "prontidao_reprovada") {
          throw new ErroModal(erro.mensagem, (erro.corpo.itens ?? []).map((i) => ({ ok: i.ok, rotulo: `${ROTULO_DO_ITEM[i.id] ?? i.id}${i.detalhe ? ` — ${i.detalhe}` : ""}` })));
        }
        if (erro.codigo === "conflito_versao" || erro.codigo === "transicao_invalida") {
          recarregar();
          throw new ErroModal(`${erro.mensagem} A ficha foi atualizada; confira o estado atual e tente de novo.`);
        }
        throw new ErroModal(erro.campos ? Object.values(erro.campos).join(" ") : erro.mensagem);
      }
    },
  });
  if (concluido) {
    avisar(`${e.nome}: ${acao.rotulo.toLowerCase()} concluído. Registrado na auditoria.`);
    recarregar();
  }
}

async function apagarDados(f, recarregar) {
  const e = f.empresa;
  let resumo;
  try {
    resumo = await api.get(caminhos.apagarResumo(e.slug));
  } catch (erro) {
    avisar(erro.mensagem);
    return;
  }
  const itens = Object.entries(resumo.contagens).filter(([, n]) => n > 0).map(([k, n]) => `${k}: ${inteiro(n)}`).join(", ");
  const feito = await abrirModal({
    titulo: `Apagar os dados de ${e.nome}?`, perigo: true, rotuloConfirmar: "Apagar dados",
    texto: `Será apagado: ${itens || "nenhum registro"}. A trilha de auditoria é mantida. Não há como desfazer.`,
    campos: [{ nome: "confirmacao", rotulo: `Digite o nome exato da empresa: ${e.nome}`, tipo: "texto", exato: e.nome }],
    aoConfirmar: async (v) => {
      try {
        await api.post(caminhos.apagar(e.slug), { confirmacao: v.confirmacao });
      } catch (erro) {
        throw new ErroModal(erro.mensagem);
      }
    },
  });
  if (feito) {
    avisar("Dados apagados. Registrado na auditoria.");
    recarregar();
  }
}

export async function montar({ conteudo, shell, rota }) {
  const slug = rota.slug;
  shell.titulo("Ficha da ", "Empresa");
  shell.acoes({ periodo: true });
  shell.periodoAtual(obter().periodo);
  const raiz = h("div", { class: "dashboard" });
  conteudo.replaceChildren(raiz);

  async function recarregar() {
    shell.periodoAtual(obter().periodo);
    trocar(raiz, carregando(4));
    let ficha;
    let nomes;
    try {
      [ficha, nomes] = await Promise.all([api.get(caminhos.empresa(slug), { periodo: obter().periodo }), nomesDosPlanos()]);
    } catch (erro) {
      if (erro?.status === 404) trocar(raiz, naoEncontrada());
      else if (erro?.status !== 401) trocar(raiz, vazio(erro.mensagem));
      return;
    }
    shell.atualizadoEm(ficha.atualizado_em);
    desenhar(ficha, nomes);
  }

  function desenhar(f, nomes) {
    const e = f.empresa;
    const botoes = [];
    if (podeOperar()) {
      if (e.estado !== "encerrado") botoes.push(h("a", { class: "btn", href: hrefs.editar(slug) }, icone("pen"), " Editar"));
      f.acoes_permitidas.forEach((a) => {
        const classe = a.para === "encerrado" ? "danger" : a.para === "ativo" ? "primary" : "";
        botoes.push(h("button", { class: `btn ${classe}`, type: "button", onclick: () => mudarEstado(f, a, recarregar) }, a.rotulo));
      });
      if (e.estado === "encerrado" && !e.dados_apagados_em) {
        botoes.push(h("button", { class: "btn danger", type: "button", onclick: () => apagarDados(f, recarregar) }, icone("trash"), " Apagar dados"));
      }
    }
    const lado = podeOperar()
      ? (botoes.length ? h("div", { class: "actions" }, botoes) : h("span", { class: "ro-note" }, icone("lock"), " Empresa encerrada: sem ações."))
      : h("span", { class: "ro-note" }, icone("eye"), " Papel de leitura: ações indisponíveis.");
    const alertas = f.atencao.map((a) => h("span", { class: "tone-warn" }, icone(visual(a.codigo).icone), ` ${a.detalhe}`));

    const grafico = h("div", { class: "chart-wrap" });
    const cartaoGrafico = cartao("Mensagens no período", null, grafico);
    trocar(raiz, 
      h("div", { class: "row" }, h("a", { class: "back", href: hrefs.empresas }, icone("arrow-left"), " Todas as empresas")),
      h("div", { class: "row" }, h("div", { class: "f-head" },
        h("div", null, h("h2", null, e.nome),
          h("div", { class: "meta" }, h("span", { class: `badge ${CLASSE_DO_ESTADO[e.estado]}` }, ESTADOS[e.estado]), h("span", null, e.slug), h("span", null, e.nicho), h("span", null, nomes[e.plano] ?? e.plano)),
          alertas.length ? h("div", { class: "meta alertas" }, alertas) : null,
          h("div", { class: "meta" }, h("a", { class: "link", href: hrefs.conversas(slug) }, icone("comments"), " Ver conversas (só metadados)"))),
        lado)),
      h("section", { class: "row r3" }, identificacao(f, nomes), prontidao(f, async () => {
        try {
          await api.post(caminhos.prontidao(slug));
          avisar("Prontidão verificada.");
          recarregar();
        } catch (erro) {
          if (erro?.status !== 401) avisar(erro.mensagem);
        }
      })),
      h("section", { class: "row r3" }, atendimento(f), custo(f)),
      f.atendimento ? h("section", { class: "row" }, cartaoGrafico) : null,
      h("section", { class: "row" }, auditoria(slug)));
    if (f.atendimento) {
      bloco(grafico, () => api.get(caminhos.serie(slug), { periodo: obter().periodo }), (s) => {
        const alvo = h("div");
        const rotulos = s.pontos.map((p) => new Date(p.inicio).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo",
          ...(obter().periodo === "hoje" ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "short" }) }).replace(".", ""));
        linha(alvo, { rotulos, series: [
          { nome: "Recebidas", valores: s.pontos.map((p) => p.recebidas), cor: "#14b8a6" },
          { nome: "Pelo agente", valores: s.pontos.map((p) => p.agente), cor: "#5eead4", tracejada: true },
        ], formatarValor: inteiro, animar: false, idGrafico: "ficha" });
        return alvo;
      });
    }
  }

  shell.aoMudarPeriodo = (p) => { definir({ periodo: p }); recarregar(); };
  await recarregar();
  return { destruir() { shell.acoes(); } };
}

