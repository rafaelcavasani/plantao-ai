// Teste de fumaça do front contra a API real, com jsdom. As dependências NÃO fazem parte do projeto: veja LEIA-ME.md.
import { JSDOM } from "jsdom";
import { webcrypto } from "node:crypto";
import { pathToFileURL } from "node:url";

const BASE = process.env.PAINEL_BASE ?? "http://127.0.0.1:8765";
const WEB = decodeURIComponent(new URL("../../apps/dashboard/web/js/", import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, "$1");

const dom = new JSDOM(`<!doctype html><html><body><div id="raiz"></div></body></html>`, { url: `${BASE}/painel/`, pretendToBeVisual: true });
const w = dom.window;
w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
w.scrollTo = () => {};
w.Element.prototype.scrollIntoView = () => {};
w.HTMLFormElement.prototype.requestSubmit = function () { this.dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true })); };
Object.assign(globalThis, {
  window: w, document: w.document, Node: w.Node, HTMLElement: w.HTMLElement, CustomEvent: w.CustomEvent,
  requestAnimationFrame: w.requestAnimationFrame.bind(w), matchMedia: w.matchMedia,
  CSS: { escape: (s) => String(s).replace(/(["\\])/g, "\\$1") },
});
globalThis.crypto ??= webcrypto;
w.confirm = () => true;

const fetchReal = globalThis.fetch;
let cookie = "";
globalThis.fetch = (url, opts = {}) => fetchReal(url, { ...opts, headers: { ...(opts.headers ?? {}), Cookie: cookie, Origin: BASE } });

let falhas = 0;
const ok = (cond, msg) => { console.log(`${cond ? "  ok  " : "FALHA "} ${msg}`); if (!cond) falhas++; };
const pausa = (ms) => new Promise((r) => setTimeout(r, ms));
async function esperar(fn, msg, ms = 6000) {
  const fim = Date.now() + ms;
  while (Date.now() < fim) { try { const v = fn(); if (v) return v; } catch { /* ainda não */ } await pausa(80); }
  ok(false, `${msg} (tempo esgotado)`);
  return null;
}
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const texto = (el) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const porTexto = (s, t, r = document) => $$(s, r).find((e) => texto(e).includes(t));
const digitar = (el, valor) => { el.value = valor; el.dispatchEvent(new w.Event("input", { bubbles: true })); };
const clicar = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
const api = async (caminho, opcoes = {}) => (await fetchReal(BASE + caminho, { ...opcoes, headers: { Cookie: cookie, Origin: BASE, "Content-Type": "application/json", ...(opcoes.headers ?? {}) } })).json();
const ir = async (hash) => { w.location.hash = hash; await pausa(150); };

// --- login (modo dev) ---
const login = await fetchReal(`${BASE}/admin/auth/entrar`, { redirect: "manual" });
cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
ok(login.status === 303 && cookie.startsWith("plantao_painel="), "login de desenvolvimento cria a sessão");

const { iniciar } = await import(pathToFileURL(WEB + "app.js").href);
await iniciar(document.getElementById("raiz"));

// --- visão geral ---
await esperar(() => $$(".kpi").length === 4, "4 KPIs aparecem");
const v = await api("/admin/visao-geral?periodo=30d");
await pausa(1500);
const kpiMsgs = texto($(".kpi .val"));
ok(kpiMsgs === new Intl.NumberFormat("pt-BR").format(v.totais.mensagens.valor), `KPI de mensagens (${kpiMsgs}) bate com a API (${v.totais.mensagens.valor})`);
ok($$(".kpi .lbl:not(.apoio)").map(texto).join("|") === "Mensagens|Conversas|Taxa de handoff|Custo (US$)", "rótulos dos KPIs");
ok(texto($(".nav .nav-item.active")) === "Visão Geral", "item de menu ativo = Visão Geral");
ok($$(".nav-item").length === 2 && !$("header.topbar nav"), "navegação só na barra lateral, nenhuma na topbar");
ok(texto($(".updated")).startsWith("Atualizado"), "texto 'Atualizado ...' na topbar");
const segs = $$("circle.seg");
ok(segs.length === 4, "donut com 4 segmentos (um por estado)");
await pausa(300);
const C = 2 * Math.PI * 70;
const soma = segs.reduce((a, s) => a + parseFloat(s.getAttribute("stroke-dasharray")), 0);
ok(Math.abs(soma - C) < 0.01, `arcos do donut fecham a circunferência (${soma.toFixed(2)} de ${C.toFixed(2)})`);
await pausa(900);
const barras = $$(".f-bar").map((b) => parseFloat(b.style.width));
ok(barras.length === 4 && barras.every((x) => x >= 20), `barras do funil >= 20% (${barras.join(", ")})`);
ok($$("table tbody tr").length === 3, "tabela com as 3 empresas");
ok(porTexto("table tbody tr", "Sorriso Vivo")?.querySelector(".flag") !== null, "empresa com atenção tem ícone");
ok($("svg.chart .halo") && $$("svg.chart circle.end-dot").length === 2, "marcas de último ponto presentes (2 séries)");
ok($$("circle.end-dot").every((c) => !c.hasAttribute("style")), "marcas do último ponto sem estilo inline (nenhuma animação de posição)");
const sparkMarca = $$("circle.end-dot")[0];
ok(sparkMarca.getAttribute("cx") && sparkMarca.getAttribute("cy"), "marca do último ponto com cx/cy fixos");

// troca de período
clicar(porTexto(".seg button", "7d"));
await esperar(() => $(".seg button.on")?.dataset.p === "7d", "período 7d selecionado");
await pausa(800);
ok($$(".kpi").length === 4, "KPIs recarregados no período 7d");

// --- empresas ---
await ir("#/empresas");
await esperar(() => texto($("h2")) === "Empresas" && $$("table tbody tr").length === 3, "tela Empresas lista 3 empresas");
ok(texto($(".nav .nav-item.active")) === "Empresas", "menu ativo = Empresas");
ok(porTexto("a.btn", "Nova empresa") !== undefined, "botão Nova empresa (papel operação)");
ok($$("a.btn").filter((a) => texto(a).includes("Editar")).length === 3, "Editar em cada empresa não encerrada");
digitar($("input[type=search]"), "studio");
await esperar(() => $$("table tbody tr").length === 1, "busca por 'studio' filtra a lista");
digitar($("input[type=search]"), "");
await esperar(() => $$("table tbody tr").length === 3, "limpar a busca volta as 3");
clicar(porTexto(".seg button", "Em configuração"));
await esperar(() => $$("table tbody tr").length === 1 && texto($("table tbody")).includes("Ótica"), "filtro 'Em configuração' mostra a Ótica");
clicar(porTexto(".seg button", "Todas"));

// --- ficha ---
await ir("#/empresa/sorriso-vivo");
await esperar(() => texto($(".f-head h2")) === "Clínica Sorriso Vivo", "ficha abre com o nome");
ok(texto(document.body).includes("Histórico de auditoria") && texto(document.body).includes("Prontidão"), "ficha tem prontidão e auditoria");
ok(!!porTexto("button.btn", "Suspender") && !!porTexto("button.btn", "Encerrar"), "ações permitidas: Suspender e Encerrar");
ok(!texto(document.body).includes("TEXTO-QUE-NAO-PODE-VAZAR"), "ficha sem texto de mensagem");

// suspender
clicar(porTexto("button.btn", "Suspender"));
await esperar(() => $(".panel[role=dialog]"), "janela de confirmação abre");
digitar($("#modal-motivo"), "teste de fumaça");
clicar(porTexto(".panel button", "Suspender"));
await esperar(() => texto($(".f-head .badge")) === "Suspenso", "estado muda para Suspenso", 8000);
ok(!!porTexto("button.btn", "Retomar"), "agora oferece Retomar");
clicar(porTexto("button.btn", "Retomar"));
await esperar(() => $(".panel[role=dialog]"), "janela de retomar abre");
clicar(porTexto(".panel button", "Retomar"));
await esperar(() => texto($(".f-head .badge")) === "Ativo", "estado volta a Ativo", 8000);
const ficha = await api("/admin/empresas/sorriso-vivo/auditoria?tamanho=5");
ok(ficha.itens.some((i) => i.campo === "status" && i.operador === "ana@exemplo.com"), "auditoria registra o e-mail do operador");

// encerrar exige o nome exato
clicar(porTexto("button.btn", "Encerrar"));
await esperar(() => $(".panel[role=dialog]"), "janela de encerrar abre");
const botaoEncerrar = $$(".panel button").find((b) => texto(b) === "Encerrar");
ok(botaoEncerrar.disabled, "botão Encerrar começa desabilitado");
digitar($("#modal-confirmacao"), "clínica sorriso vivo");
ok(botaoEncerrar.disabled, "nome com maiúsculas diferentes não habilita");
digitar($("#modal-confirmacao"), "Clínica Sorriso Vivo ");
ok(botaoEncerrar.disabled, "nome com espaço sobrando não habilita");
digitar($("#modal-confirmacao"), "Clínica Sorriso Vivo");
ok(!botaoEncerrar.disabled, "nome exato habilita");
document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
await esperar(() => !$(".panel[role=dialog]"), "Esc fecha a janela sem encerrar");
ok((await api("/admin/empresas/sorriso-vivo")).empresa.estado === "ativo", "empresa continua ativa");

// ativação reprovada (Ótica em configuração)
await ir("#/empresa/otica-visao-nova");
await esperar(() => texto($(".f-head h2")) === "Ótica Visão Nova", "ficha da Ótica");
clicar(porTexto("button.btn", "Ativar"));
await esperar(() => $(".panel[role=dialog]"), "janela de ativar abre");
clicar($$(".panel button").find((b) => texto(b) === "Ativar"));
await esperar(() => $(".erro-modal:not([hidden])"), "ativação reprovada mostra erro na janela");
ok($$(".erro-modal li").length === 4, "lista os 4 itens da prontidão");
document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

// --- formulário: nova empresa ---
await ir("#/empresas/nova");
await esperar(() => $("#form-empresa"), "formulário de nova empresa");
digitar($("#f-nome"), "Pet Care Moema");
ok($("#f-slug").value === "pet-care-moema", "slug sugerido a partir do nome");
digitar($("#f-nicho"), "Pet shop");
digitar($("#f-instancia"), "petcare-wa");
digitar($("#f-segredo"), "curto");
digitar($("#f-chave"), "chave");
$("#form-empresa").requestSubmit();
await pausa(300);
ok($("[data-campo='conexao.segredo_entrega']").classList.contains("invalid"), "segredo curto: erro no campo");
ok(texto($("[data-campo='conexao.segredo_entrega'] .err")).includes("32"), "mensagem cita 32 caracteres");
ok(document.activeElement === $("#f-segredo"), "foco vai para o primeiro campo com erro");
digitar($("#f-segredo"), "s".repeat(40));
digitar($("#f-desconto"), "150");
$("#form-empresa").requestSubmit();
await pausa(300);
ok($("[data-campo='configuracao.limite_desconto_percentual']").classList.contains("invalid"), "desconto fora da faixa: erro no campo");
digitar($("#f-desconto"), "10");
const dias = $$(".hours input");
ok(dias.length === 7, "sete campos de horário");
digitar(dias[0], "8h-18h");
$("#form-empresa").requestSubmit();
await pausa(300);
ok(texto($("[data-campo='configuracao.horario_funcionamento'] .err")).startsWith("Segunda"), "horário inválido: erro cita o dia");
digitar(dias[0], "08:00-18:00"); digitar(dias[6], "fechado");
$("#form-empresa").requestSubmit();
await esperar(() => w.location.hash === "#/empresa/pet-care-moema", "criação redireciona para a ficha", 8000);
await esperar(() => texto($(".f-head h2")) === "Pet Care Moema", "ficha da nova empresa");
const criada = await api("/admin/empresas/pet-care-moema");
ok(criada.empresa.estado === "em_configuracao" && criada.conexao?.instancia === "petcare-wa", "empresa criada em configuração com a conexão");
ok(!JSON.stringify(criada).includes("s".repeat(40)), "segredo não volta na ficha");

// slug repetido: erro do servidor no campo
await ir("#/empresas/nova");
await esperar(() => $("#form-empresa"), "novo formulário");
digitar($("#f-nome"), "Outra Pet");
digitar($("#f-slug"), "pet-care-moema");
digitar($("#f-nicho"), "Pet shop");
$("#form-empresa").requestSubmit();
await esperar(() => $("[data-campo='slug']")?.classList.contains("invalid"), "slug repetido: erro do servidor no campo");
ok(texto($("[data-campo='slug'] .err")).includes("Já existe"), "mensagem do servidor em português");

// --- formulário: edição ---
await ir("#/empresa/pet-care-moema/editar");
await esperar(() => $("#form-empresa") && $("#f-nome")?.value === "Pet Care Moema", "formulário de edição carregado");
ok($("#f-slug").hasAttribute("readonly"), "slug somente leitura na edição");
ok(!!$(".secret-ok") && texto($(".secret-ok")).includes("credenciais configuradas"), "credenciais só como 'configuradas'");
ok(!$$("input").some((i) => i.value.includes("s".repeat(40))), "nenhum campo traz o segredo");
$("#form-empresa").requestSubmit();
await pausa(400);
ok($$(".toast").some((t) => texto(t).includes("Nenhuma alteração")), "salvar sem mudanças avisa e não chama a API");
digitar($("#f-desconto"), "5");
$("#form-empresa").requestSubmit();
await esperar(() => w.location.hash === "#/empresa/pet-care-moema", "edição volta para a ficha", 8000);
await pausa(500);
const aud = await api("/admin/empresas/pet-care-moema/auditoria?tamanho=5");
ok(aud.itens.some((i) => i.campo === "limite_desconto_percentual" && i.valor_novo === 5), "auditoria só do campo alterado");

// --- conversas (só metadados) ---
await ir("#/empresa/sorriso-vivo/conversas");
await esperar(() => $$("table tbody tr").length >= 1, "lista de conversas");
ok(!texto(document.body).includes("TEXTO-QUE-NAO-PODE-VAZAR") && !texto(document.body).includes("98888"), "conversas sem texto nem contato");
clicar($("table tbody a.link"));
await esperar(() => texto(document.body).includes("Linha do tempo"), "detalhe da conversa");
ok(!texto(document.body).includes("TEXTO-QUE-NAO-PODE-VAZAR"), "detalhe sem texto de mensagem");

// --- rota desconhecida e sessão ---
await ir("#/empresa/nao-existe");
await esperar(() => texto(document.body).includes("Empresa não encontrada"), "empresa inexistente: 'Empresa não encontrada'");
await ir("#/qualquer-coisa");
await esperar(() => texto(document.body).includes("Página não encontrada"), "rota desconhecida: 'Página não encontrada'");
cookie = "plantao_painel=forjado";
await ir("#/empresas");
await esperar(() => texto(document.body).includes("Entrar") && texto(document.body).includes("sessão terminou"), "sessão inválida volta ao login com aviso");

console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTudo certo");
process.exit(falhas ? 1 : 0);
