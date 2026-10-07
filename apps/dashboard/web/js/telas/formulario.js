// Cadastro e edição de empresa (US4): identificação, configuração do atendimento, conexão do canal e documentos.
// As validações do cliente repetem as do servidor (validar.js); os erros do servidor aparecem no mesmo campo.

import { api, caminhos, ErroApi } from "../api.js";
import { NICHOS_SUGERIDOS, planos } from "../catalogo.js";
import { campo, grupo, mostrarErros } from "../componentes/campo.js";
import { carregando, naoEncontrada, semPermissao, vazio } from "../componentes/estados.js";
import { avisar } from "../componentes/toast.js";
import { h, icone } from "../dom.js";
import { podeOperar } from "../estado.js";
import { inteiro } from "../formatar.js";
import { hrefs, ir } from "../rotas.js";
import {
  DIAS, ORDEM_DOS_CAMPOS, SEGREDO_MIN, TAMANHO_MAXIMO_ARQUIVO, slugificar, triarArquivos,
  validarFormulario,
} from "../validar.js";

const DICAS_DE_STATUS = {
  ok: "indexado", inalterado: "já estava atualizado", sem_texto: "sem texto aproveitável",
  arquivo_grande: "arquivo grande demais", nao_suportado: "formato não suportado", falha: "falha ao indexar",
  processando: "processando...",
};

const lista = (texto) => String(texto ?? "").split(",").map((t) => t.trim()).filter(Boolean);
const numero = (texto) => Number(String(texto).trim().replace(",", "."));
const bytesParaBase64 = async (arquivo) => {
  const buffer = new Uint8Array(await arquivo.arrayBuffer());
  let binario = "";
  for (let i = 0; i < buffer.length; i += 0x8000) binario += String.fromCharCode(...buffer.subarray(i, i + 0x8000));
  return btoa(binario);
};

/** Valores iniciais do formulário (nova empresa ou empresa carregada). */
function iniciais(ficha, config) {
  const c = config ?? {};
  const horario = c.horario_funcionamento ?? {};
  return {
    nome: ficha?.empresa.nome ?? "",
    slug: ficha?.empresa.slug ?? "",
    nicho: ficha?.empresa.nicho ?? "",
    plano: ficha?.empresa.plano ?? "recepcionista",
    tom_de_voz: c.tom_de_voz ?? "Cordial, objetivo e profissional. Trata o cliente por você.",
    horario: Object.fromEntries(Object.entries(horario)),
    limite_desconto_percentual: String(c.limite_desconto_percentual ?? 10),
    confianca_minima_handoff: String(c.confianca_minima_handoff ?? 0.7),
    topicos_proibidos: (c.topicos_proibidos ?? []).join(", "),
    palavras_gatilho: (c.palavras_gatilho ?? ["procon", "processo", "advogado"]).join(", "),
    limite_mensagens_por_minuto: String(c.limite_mensagens_por_minuto ?? 20),
    handoff_ttl_minutos: String(c.handoff_ttl_minutos ?? 120),
  };
}

export async function montar({ conteudo, shell, rota }) {
  const editar = rota.modo === "editar";
  shell.titulo(editar ? "Editar " : "Nova ", "Empresa");
  shell.acoes();
  const voltar = editar ? hrefs.ficha(rota.slug) : hrefs.empresas;
  const cabecalho = h("div", { class: "row" }, h("a", { class: "back", href: voltar }, icone("arrow-left"), editar ? " Voltar para a ficha" : " Empresas"));
  const raiz = h("div", { class: "dashboard" }, cabecalho);
  conteudo.replaceChildren(raiz);

  if (!podeOperar()) {
    raiz.append(semPermissao("O papel de leitura não permite cadastrar nem editar empresas."));
    return { destruir() {} };
  }
  raiz.append(carregando(4));

  let ficha = null;
  let config = null;
  let catalogo;
  try {
    [catalogo, ficha, config] = await Promise.all([
      planos(),
      editar ? api.get(caminhos.empresa(rota.slug)) : null,
      editar ? api.get(caminhos.configuracao(rota.slug)) : null,
    ]);
  } catch (erro) {
    raiz.replaceChildren(cabecalho, erro?.status === 404 ? naoEncontrada() : vazio(erro?.mensagem ?? "Não foi possível abrir o formulário."));
    return { destruir() {} };
  }
  if (editar && ficha.empresa.estado === "encerrado") {
    raiz.replaceChildren(cabecalho, semPermissao("Empresa encerrada: não pode ser editada."));
    return { destruir() {} };
  }

  const base = iniciais(ficha, config?.configuracao);
  let versao = ficha?.empresa.versao ?? null;
  let sujo = false;
  let enviando = false;
  let arquivos = [];
  const temConexao = Boolean(ficha?.conexao);
  let trocandoConexao = !temConexao;

  // --- Controles ---
  const nome = h("input", { id: "f-nome", type: "text", maxlength: 255, autocomplete: "off", value: base.nome });
  const slug = h("input", { id: "f-slug", type: "text", maxlength: 63, autocomplete: "off", spellcheck: "false", value: base.slug, readonly: editar });
  let slugTocado = editar;
  slug.addEventListener("input", () => { slugTocado = true; });
  nome.addEventListener("input", () => { if (!slugTocado) slug.value = slugificar(nome.value); });
  const nicho = h("input", { id: "f-nicho", type: "text", maxlength: 100, list: "nichos", autocomplete: "off", value: base.nicho });
  const nichos = h("datalist", { id: "nichos" }, NICHOS_SUGERIDOS.map((n) => h("option", { value: n })));
  const plano = h("select", { id: "f-plano" }, catalogo.map((p) => h("option", { value: p.chave, selected: p.chave === base.plano }, p.nome)));
  const tom = h("textarea", { id: "f-tom", rows: 3 }, base.tom_de_voz);
  const diasExtras = Object.keys(base.horario).filter((d) => !DIAS.some(([k]) => k === d));
  const horario = new Map();
  const campoHorario = (chave, rotulo) => {
    const input = h("input", { type: "text", placeholder: "08:00-18:00", value: base.horario[chave] ?? "", "aria-label": `Horário de ${rotulo}` });
    horario.set(chave, input);
    return h("label", { class: "dia" }, rotulo, input);
  };
  const horarios = h("div", { class: "hours" }, DIAS.map(([k, r]) => campoHorario(k, r)), diasExtras.map((k) => campoHorario(k, k)));
  const desconto = h("input", { id: "f-desconto", type: "text", inputmode: "decimal", value: base.limite_desconto_percentual });
  const confianca = h("input", { id: "f-confianca", type: "text", inputmode: "decimal", value: base.confianca_minima_handoff });
  const proibidos = h("input", { id: "f-proibidos", type: "text", value: base.topicos_proibidos });
  const gatilho = h("input", { id: "f-gatilho", type: "text", value: base.palavras_gatilho });
  const rpm = h("input", { id: "f-rpm", type: "text", inputmode: "numeric", value: base.limite_mensagens_por_minuto });
  const ttl = h("input", { id: "f-ttl", type: "text", inputmode: "numeric", value: base.handoff_ttl_minutos });
  const instancia = h("input", { id: "f-instancia", type: "text", maxlength: 100, autocomplete: "off", value: "" });
  const segredo = h("input", { id: "f-segredo", type: "password", autocomplete: "new-password", spellcheck: "false" });
  const chave = h("input", { id: "f-chave", type: "password", autocomplete: "new-password", spellcheck: "false" });
  const gerar = h("button", { class: "btn sm", type: "button", onclick: () => {
    const bytes = crypto.getRandomValues(new Uint8Array(24));
    segredo.value = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    segredo.type = "text";
    sujo = true;
  } }, "Gerar");
  const olho = h("button", { class: "btn sm", type: "button", "aria-label": "Mostrar ou ocultar o segredo",
    onclick: () => { segredo.type = segredo.type === "password" ? "text" : "password"; } }, icone("eye"));

  const resumoDeErros = h("div", { class: "erro-bloco", role: "alert", hidden: true });
  const faixaDeConflito = h("div", { class: "conflito", role: "alert", hidden: true });
  const resultadoDocs = h("ul", { class: "files resultado" });
  const listaArquivos = h("ul", { class: "files" });
  const recusados = h("p", { class: "err", role: "alert" });
  const entradaArquivo = h("input", { type: "file", multiple: true, hidden: true, accept: ".md,.txt,.pdf" });

  // --- Blocos ---
  const cartao = (titulo, apoio, ...filhos) => h("article", { class: "card sem-animacao" },
    h("div", { class: "card-head" }, h("h2", null, titulo), apoio ? h("small", null, apoio) : null), ...filhos);

  const blocoIdentificacao = cartao("Identificação", editar ? "o slug não muda depois de criado" : "todos os campos são obrigatórios",
    h("div", { class: "form-grid" },
      campo({ chave: "nome", rotulo: "Nome da empresa", controle: nome, largo: true }),
      campo({ chave: "slug", rotulo: "Slug (identificador)", controle: slug, dica: "Minúsculas, números e hífen. Usado pelo operador e na auditoria." }),
      campo({ chave: "nicho", rotulo: "Nicho", controle: nicho }), nichos,
      campo({ chave: "plano", rotulo: "Plano", controle: plano })));

  const blocoConfig = cartao("Configuração do atendimento", "mudanças vão para a auditoria",
    h("div", { class: "form-grid" },
      campo({ chave: "configuracao.tom_de_voz", rotulo: "Tom de voz", controle: tom, largo: true }),
      grupo({ chave: "configuracao.horario_funcionamento", rotulo: "Horário de funcionamento", filhos: [horarios],
        dica: 'Formato HH:MM-HH:MM, ou "fechado". Dia em branco = sem atendimento.' }),
      campo({ chave: "configuracao.limite_desconto_percentual", rotulo: "Limite de desconto (%)", controle: desconto }),
      campo({ chave: "configuracao.confianca_minima_handoff", rotulo: "Confiança mínima para o agente responder", controle: confianca,
        dica: "De 0 a 1. Abaixo disso o atendimento passa para uma pessoa." }),
      campo({ chave: "configuracao.topicos_proibidos", rotulo: "Tópicos proibidos", controle: proibidos, dica: "Separados por vírgula." }),
      campo({ chave: "configuracao.palavras_gatilho", rotulo: "Palavras-gatilho de handoff", controle: gatilho, dica: "Separadas por vírgula." }),
      campo({ chave: "configuracao.limite_mensagens_por_minuto", rotulo: "Limite de mensagens por minuto", controle: rpm }),
      campo({ chave: "configuracao.handoff_ttl_minutos", rotulo: "Duração do handoff (minutos)", controle: ttl })));

  const camposDeConexao = h("div", { class: "form-grid", hidden: !trocandoConexao },
    campo({ chave: "conexao.instancia", rotulo: "Nome da instância", controle: instancia, largo: true }),
    h("div", { class: "field", dataset: { campo: "conexao.segredo_entrega" } },
      h("label", { for: "f-segredo" }, "Segredo de entrega do webhook"),
      h("div", { class: "input-row" }, segredo, gerar, olho),
      h("span", { class: "hint" }, `Mínimo de ${SEGREDO_MIN} caracteres. Guardado só como hash.`), h("span", { class: "err", role: "alert" })),
    campo({ chave: "conexao.chave_envio", rotulo: "Chave de envio", controle: chave, dica: "Guardada cifrada. Não pode ser lida depois." }));
  const resumoDaConexao = temConexao ? h("div", { class: "secret-ok", hidden: trocandoConexao },
    h("span", null, icone("shield-halved", "tone-ok"), ` Instância `, h("b", null, ficha.conexao.instancia), " com credenciais configuradas. Os valores nunca são exibidos."),
    h("button", { class: "btn sm", type: "button", onclick: () => {
      trocandoConexao = true; resumoDaConexao.hidden = true; camposDeConexao.hidden = false; instancia.value = ficha.conexao.instancia; instancia.focus(); sujo = true;
    } }, "Substituir credenciais")) : null;
  const blocoConexao = cartao("Conexão do canal", "WhatsApp via Evolution API",
    resumoDaConexao,
    editar && temConexao ? h("p", { class: "foot-note" }, "Trocar as credenciais exige nova verificação da conexão.") : null,
    !temConexao ? h("p", { class: "foot-note" }, "Opcional agora: a empresa nasce em configuração e a conexão pode ser cadastrada depois.") : null,
    camposDeConexao);

  const pintarArquivos = () => {
    listaArquivos.replaceChildren(...arquivos.map((a, i) => h("li", null, icone("file-lines"), a.name,
      h("span", null, `${(a.size / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KB`),
      h("button", { type: "button", "aria-label": `Remover ${a.name}`, onclick: () => { arquivos.splice(i, 1); pintarArquivos(); } }, icone("xmark")))));
  };
  entradaArquivo.addEventListener("change", () => {
    const { aceitos, recusados: ruins } = triarArquivos([...entradaArquivo.files], arquivos);
    arquivos.push(...aceitos);
    recusados.textContent = ruins.length ? `Recusados: ${ruins.map((r) => `${r.nome} (${r.motivo})`).join("; ")}.` : "";
    entradaArquivo.value = "";
    if (aceitos.length) sujo = true;
    pintarArquivos();
  });
  const apoioBase = ficha?.base ? `${inteiro(ficha.base.documentos)} documentos e ${inteiro(ficha.base.trechos)} trechos já indexados` : "nenhum documento ainda";
  const blocoDocs = cartao("Base de conhecimento", apoioBase,
    h("label", { class: "drop" }, icone("cloud-arrow-up"),
      h("span", null, "Clique para escolher arquivos ", h("b", null, ".md"), ", ", h("b", null, ".txt"), " ou ", h("b", null, ".pdf"),
        ` (até ${TAMANHO_MAXIMO_ARQUIVO / 1024 / 1024} MB cada, no máximo 10 por vez)`), entradaArquivo),
    recusados, listaArquivos, resultadoDocs);

  const botaoSalvar = h("button", { class: "btn primary", type: "submit" }, editar ? "Salvar alterações" : "Criar empresa");
  const rodape = h("div", { class: "form-foot" },
    h("span", { class: "note" }, editar ? "Salvar não muda o estado da empresa." : "A empresa nasce em configuração. Ative depois que a prontidão for aprovada."),
    h("a", { class: "btn", href: voltar }, "Cancelar"), botaoSalvar);
  const formulario = h("form", { id: "form-empresa", novalidate: true, class: "form" },
    resumoDeErros, faixaDeConflito, blocoIdentificacao, blocoConfig, blocoConexao, blocoDocs, rodape);
  raiz.replaceChildren(cabecalho, formulario);

  formulario.addEventListener("input", () => { sujo = true; });

  // --- Coleta e envio ---
  const conexaoPreenchida = () => trocandoConexao && [instancia, segredo, chave].some((c) => c.value !== "");
  function coletar() {
    const valores = {
      nome: nome.value.trim(), slug: slug.value.trim(), nicho: nicho.value.trim(), plano: plano.value,
      tom_de_voz: tom.value, horario: Object.fromEntries([...horario].map(([k, el]) => [k, el.value])),
      limite_desconto_percentual: desconto.value, confianca_minima_handoff: confianca.value,
      limite_mensagens_por_minuto: rpm.value, handoff_ttl_minutos: ttl.value,
      topicos_proibidos: proibidos.value, palavras_gatilho: gatilho.value,
    };
    if (conexaoPreenchida()) valores.conexao = { instancia: instancia.value.trim(), segredo_entrega: segredo.value, chave_envio: chave.value };
    return valores;
  }

  function configuracaoParaApi(v) {
    const horarioApi = {};
    for (const [dia, texto] of Object.entries(v.horario)) if (texto.trim()) horarioApi[dia] = texto.trim();
    return {
      tom_de_voz: v.tom_de_voz.trim(), horario_funcionamento: horarioApi,
      limite_desconto_percentual: numero(v.limite_desconto_percentual), confianca_minima_handoff: numero(v.confianca_minima_handoff),
      topicos_proibidos: lista(v.topicos_proibidos), palavras_gatilho: lista(v.palavras_gatilho),
      limite_mensagens_por_minuto: numero(v.limite_mensagens_por_minuto), handoff_ttl_minutos: numero(v.handoff_ttl_minutos),
    };
  }

  const mudouAlgo = (v) => {
    const antes = iniciais(ficha, config?.configuracao);
    const normal = (x) => JSON.stringify([x.nome, x.nicho, x.plano, x.tom_de_voz.trim(), lista(x.topicos_proibidos), lista(x.palavras_gatilho),
      numero(x.limite_desconto_percentual), numero(x.confianca_minima_handoff), numero(x.limite_mensagens_por_minuto), numero(x.handoff_ttl_minutos),
      Object.fromEntries(Object.entries(x.horario).map(([d, t]) => [d, t.trim().toLowerCase()]).filter(([, t]) => t && t !== "fechado").sort())]);
    return normal(v) !== normal(antes) || Boolean(v.conexao) || arquivos.length > 0;
  };

  function mostrar(erros) {
    const foco = mostrarErros(formulario, erros, ORDEM_DOS_CAMPOS);
    const soltos = Object.entries(erros).filter(([k]) => !formulario.querySelector(`[data-campo="${CSS.escape(k)}"]`));
    resumoDeErros.hidden = soltos.length === 0;
    resumoDeErros.replaceChildren(...soltos.map(([k, m]) => h("p", null, icone("triangle-exclamation", "tone-warn"), ` ${k}: ${m}`)));
    foco?.focus();
  }

  function aoErroDoServidor(erro) {
    if (erro.codigo === "conflito_versao") return mostrarConflito(erro.corpo.atual);
    if (erro.campos) return mostrar(erro.campos);
    resumoDeErros.hidden = false;
    resumoDeErros.replaceChildren(h("p", null, icone("triangle-exclamation", "tone-crit"), ` ${erro.mensagem}`));
    resumoDeErros.scrollIntoView?.({ block: "center" });
    return undefined;
  }

  function mostrarConflito(atual) {
    versao = atual.versao;
    faixaDeConflito.hidden = false;
    faixaDeConflito.replaceChildren(
      h("p", null, icone("triangle-exclamation", "tone-warn"), " Esta empresa foi alterada por outra pessoa enquanto você editava. Veja os valores atuais antes de decidir."),
      h("dl", { class: "kv" },
        h("div", null, h("dt", null, "Nome"), h("dd", null, atual.nome)),
        h("div", null, h("dt", null, "Estado"), h("dd", null, atual.estado)),
        h("div", null, h("dt", null, "Tom de voz"), h("dd", null, atual.configuracao?.tom_de_voz ?? "—")),
        h("div", null, h("dt", null, "Limite de desconto"), h("dd", null, `${atual.configuracao?.limite_desconto_percentual ?? "—"}%`))),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: () => { sujo = false; window.location.reload(); } }, icone("rotate-right"), " Recarregar os valores atuais"),
        h("button", { class: "btn primary", type: "button", onclick: () => { faixaDeConflito.hidden = true; formulario.requestSubmit(); } }, "Salvar mesmo assim")));
    faixaDeConflito.scrollIntoView?.({ block: "center" });
  }

  async function enviarDocumentos(slugDaEmpresa) {
    if (!arquivos.length) return { ok: 0, problemas: 0 };
    const lote = [];
    for (const a of arquivos) lote.push({ nome: a.name, conteudo_base64: await bytesParaBase64(a) });
    const { remessa } = await api.post(caminhos.documentos(slugDaEmpresa), { arquivos: lote });
    resultadoDocs.replaceChildren(...arquivos.map((a) => h("li", null, icone("file-lines"), a.name, h("span", null, DICAS_DE_STATUS.processando))));
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const r = await api.get(caminhos.remessa(slugDaEmpresa, remessa));
      if (r.estado !== "concluida") continue;
      resultadoDocs.replaceChildren(...r.arquivos.map((a) => h("li", null,
        icone(a.status === "ok" || a.status === "inalterado" ? "circle-check" : "circle-xmark", a.status === "ok" || a.status === "inalterado" ? "tone-ok" : "tone-crit"),
        a.nome, h("span", null, `${DICAS_DE_STATUS[a.status] ?? a.status}${a.trechos ? ` · ${a.trechos} trechos` : ""}`))));
      const ruins = r.arquivos.filter((a) => !["ok", "inalterado"].includes(a.status)).length;
      return { ok: r.arquivos.length - ruins, problemas: ruins };
    }
    return { ok: 0, problemas: arquivos.length, demorou: true };
  }

  formulario.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (enviando) return;
    const v = coletar();
    const erros = validarFormulario(v, { modo: editar ? "editar" : "nova" });
    if (trocandoConexao && !temConexao && !conexaoPreenchida()) delete erros["conexao.instancia"]; // conexão é opcional ao criar
    if (Object.keys(erros).length) return mostrar(erros);
    mostrar({});
    if (editar && !mudouAlgo(v)) return avisar("Nenhuma alteração para salvar.");

    enviando = true;
    botaoSalvar.disabled = true;
    botaoSalvar.textContent = "Salvando...";
    try {
      const conexaoApi = v.conexao && { instancia: v.conexao.instancia, segredo_entrega: v.conexao.segredo_entrega, chave_envio: v.conexao.chave_envio };
      let slugFinal = v.slug;
      if (editar) {
        slugFinal = rota.slug;
        const r = await api.patch(caminhos.empresa(slugFinal), { versao, slug: slugFinal, nome: v.nome, nicho: v.nicho, plano: v.plano, configuracao: configuracaoParaApi(v) });
        versao = r.empresa.versao;
        if (conexaoApi) await api.put(caminhos.conexao(slugFinal), { versao, ...conexaoApi });
      } else {
        await api.post(caminhos.empresas, { nome: v.nome, slug: v.slug, nicho: v.nicho, plano: v.plano, configuracao: configuracaoParaApi(v), conexao: conexaoApi ?? null });
      }
      sujo = false;
      const docs = await enviarDocumentos(slugFinal);
      avisar(editar ? `${v.nome} atualizada. Registrado na auditoria.` : `${v.nome} criada em configuração.`);
      if (docs.problemas || docs.demorou) {
        resumoDeErros.hidden = false;
        resumoDeErros.replaceChildren(h("p", null, icone("triangle-exclamation", "tone-warn"),
          docs.demorou ? " A indexação está demorando; acompanhe pela ficha." : " Alguns documentos não foram indexados; veja o resultado acima."),
        h("a", { class: "btn sm", href: hrefs.ficha(slugFinal) }, "Ir para a ficha"));
        botaoSalvar.textContent = "Salvo";
      } else {
        ir(hrefs.ficha(slugFinal));
      }
    } catch (erro) {
      if (erro instanceof ErroApi) aoErroDoServidor(erro);
      else throw erro;
      botaoSalvar.disabled = false;
      botaoSalvar.textContent = editar ? "Salvar alterações" : "Criar empresa";
    } finally {
      enviando = false;
    }
  });

  const antesDeSair = (e) => { if (sujo) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", antesDeSair);
  return {
    podeSair: () => !sujo || window.confirm("Há alterações não salvas. Sair mesmo assim?"),
    destruir() { window.removeEventListener("beforeunload", antesDeSair); shell.acoes(); },
  };
}

