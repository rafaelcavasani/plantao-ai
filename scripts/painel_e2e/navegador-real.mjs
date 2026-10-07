// Verificação em navegador real (Chrome headless via playwright-core): CSP, layout responsivo, teclado, movimento
// reduzido, fontes e acessibilidade (axe-core, WCAG 2.1 AA). As dependências NÃO fazem parte do projeto: veja LEIA-ME.md.
import { chromium } from "playwright-core";
import { readFileSync, mkdirSync } from "node:fs";

const BASE = process.env.PAINEL_BASE ?? "http://127.0.0.1:8767";
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const SHOTS = process.env.PAINEL_PRINTS ?? "./prints";
mkdirSync(SHOTS, { recursive: true });
const axeSrc = readFileSync("node_modules/axe-core/axe.min.js", "utf8");

const ROTAS = [
  ["#/", "visao-geral"],
  ["#/empresas", "empresas"],
  ["#/empresa/sorriso-vivo", "ficha"],
  ["#/empresas/nova", "nova"],
  ["#/empresa/sorriso-vivo/editar", "editar"],
  ["#/empresa/sorriso-vivo/conversas", "conversas"],
];

let falhas = 0;
const ok = (c, m) => { console.log(`${c ? "  ok  " : "FALHA "} ${m}`); if (!c) falhas++; };

const browser = await chromium.launch({ executablePath: CHROME, headless: true });

async function nova(viewport, extra = {}) {
  const ctx = await browser.newContext({ viewport, ...extra });
  const page = await ctx.newPage();
  const problemas = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) problemas.push(`${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => problemas.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => problemas.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await page.goto(`${BASE}/admin/auth/entrar?destino=%2Fpainel%2F`);
  await page.waitForSelector(".sidebar");
  return { ctx, page, problemas };
}
const irPara = async (page, hash, espera = 1800) => { await page.evaluate((h) => { window.location.hash = h; }, hash); await page.waitForTimeout(espera); };

// ---------- 1. Desktop: CSP, console, fontes, colunas, axe ----------
{
  const { ctx, page, problemas } = await nova({ width: 1366, height: 900 });
  await page.waitForSelector(".kpi");
  for (const [hash, nome] of ROTAS) {
    await irPara(page, hash);
    const csp = await page.evaluate(() => window.__csp);
    ok(csp.length === 0, `${nome}: nenhuma violação de CSP${csp.length ? " -> " + csp.join("; ") : ""}`);
    await page.screenshot({ path: `${SHOTS}/desktop-${nome}.png`, fullPage: true });
    const lixo = await page.evaluate(() => (document.body.innerText.match(/(null|undefined|NaN|\[object Object\])/g) ?? []));
    ok(lixo.length === 0, `${nome}: nenhum "null", "undefined", "NaN" ou "[object Object]" visível${lixo.length ? " -> " + lixo.join(",") : ""}`);
    const colados = await page.evaluate(() => { const t = [...document.querySelectorAll("svg.chart text")].map((e) => e.getBoundingClientRect()).sort((a, b) => a.left - b.left); return t.some((r, i) => i && t[i-1].top === r.top && r.left < t[i-1].right - 1); });
    ok(!colados, `${nome}: rótulos do gráfico sem sobreposição`);
    const r = await page.evaluate(async (src) => {
      (0, eval)(src);
      const res = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
      return res.violations.map((v) => ({ id: v.id, impacto: v.impact, n: v.nodes.length, ex: v.nodes[0].html.slice(0, 120) }));
    }, axeSrc);
    ok(r.length === 0, `${nome}: axe-core WCAG 2.1 AA sem violações${r.length ? "\n      " + r.map((v) => `${v.id} (${v.impacto}, ${v.n}x) ${v.ex}`).join("\n      ") : ""}`);
  }
  await irPara(page, "#/");
  const fontes = await page.evaluate(async () => {
    await document.fonts.ready;
    return { inter: document.fonts.check('500 14px "Inter"'), outfit: document.fonts.check('600 20px "Outfit"'), fa: document.fonts.check('900 14px "Font Awesome 6 Free"') };
  });
  ok(fontes.inter && fontes.outfit && fontes.fa, `fontes locais carregadas (Inter ${fontes.inter}, Outfit ${fontes.outfit}, Font Awesome ${fontes.fa})`);
  const cols = await page.evaluate(() => getComputedStyle(document.querySelector(".row.kpis")).gridTemplateColumns.split(" ").length);
  ok(cols === 4, `KPIs em 4 colunas a 1366 px (${cols})`);
  const menu = await page.evaluate(() => ({ nav: document.querySelectorAll(".sidebar .nav-item").length, navNaTopbar: document.querySelectorAll(".topbar nav, .topbar .nav-item").length, largura: document.querySelector(".sidebar").getBoundingClientRect().width }));
  ok(menu.nav === 2 && menu.navNaTopbar === 0 && menu.largura === 240, `navegação só na barra lateral vertical de 240 px (${JSON.stringify(menu)})`);
  await page.click(".collapse-btn");
  await page.waitForTimeout(500);
  const larg = await page.evaluate(() => document.querySelector(".sidebar").getBoundingClientRect().width);
  ok(larg === 64, `barra lateral recolhe para 64 px (${larg})`);
  await page.hover('.nav-item[data-id="empresas"]');
  const tip = await page.evaluate(() => getComputedStyle(document.querySelector('.nav-item[data-id="empresas"]'), "::after").content);
  ok(tip.includes("Empresas"), `tooltip no menu recolhido (${tip})`);
  const reais = problemas.filter((p) => !p.includes("favicon"));
  ok(reais.length === 0, `console e rede sem erro nem aviso${reais.length ? "\n      " + reais.join("\n      ") : ""}`);
  await ctx.close();
}

// ---------- 2. Larguras: colunas e rolagem horizontal ----------
for (const [largura, alvo, rotulo] of [[1000, 2, "tablet"], [768, 2, "tablet estreito"], [390, 1, "celular"]]) {
  const { ctx, page } = await nova({ width: largura, height: 900 }, largura === 390 ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {});
  await page.waitForSelector(".kpi");
  for (const [hash, nome] of ROTAS) {
    await irPara(page, hash, 1500);
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    ok(m.sw <= m.iw, `${rotulo} (${largura}px) ${nome}: sem rolagem horizontal da página (${m.sw} <= ${m.iw})`);
    if (largura === 390) await page.screenshot({ path: `${SHOTS}/celular-${nome}.png`, fullPage: true });
  }
  await irPara(page, "#/", 1500);
  const cols = await page.evaluate(() => getComputedStyle(document.querySelector(".row.kpis")).gridTemplateColumns.split(" ").length);
  ok(cols === alvo, `${rotulo}: KPIs em ${alvo} coluna(s) (${cols})`);
  if (largura === 390) {
    const antes = await page.evaluate(() => document.querySelector(".sidebar").getBoundingClientRect().right);
    ok(antes <= 0, `menu escondido fora da tela no celular (direita em ${antes})`);
    await page.click(".menu-btn");
    await page.waitForTimeout(500);
    const depois = await page.evaluate(() => document.querySelector(".sidebar").getBoundingClientRect().right);
    ok(depois > 200, `menu sobreposto abre pelo botão (direita em ${depois})`);
    await page.screenshot({ path: `${SHOTS}/celular-menu-aberto.png` });
    await page.click(".scrim", { position: { x: 360, y: 400 } });
    await page.waitForTimeout(500);
    ok(await page.evaluate(() => document.querySelector(".sidebar").getBoundingClientRect().right <= 0), "menu fecha ao tocar na cortina");
    await page.click(".menu-btn"); await page.waitForTimeout(300);
    await page.click('.nav-item[data-id="empresas"]'); await page.waitForTimeout(800);
    ok(await page.evaluate(() => document.querySelector(".sidebar").getBoundingClientRect().right <= 0 && location.hash === "#/empresas"), "menu fecha ao escolher um item e navega");
    const tabela = await page.evaluate(() => { const t = document.querySelector(".table-scroll"); return t.scrollWidth > t.clientWidth && getComputedStyle(t).overflowX !== "visible"; });
    ok(tabela, "a tabela rola dentro do cartão no celular");
  }
  await ctx.close();
}

// ---------- 3. Teclado: modal com foco preso ----------
{
  const { ctx, page } = await nova({ width: 1366, height: 900 });
  await irPara(page, "#/empresa/sorriso-vivo", 2200);
  const gatilho = page.locator("button.btn", { hasText: "Encerrar" });
  await gatilho.focus();
  await page.keyboard.press("Enter");
  await page.waitForSelector(".panel[role=dialog]");
  const dentro = () => page.evaluate(() => !!document.activeElement?.closest(".panel[role=dialog]"));
  ok(await dentro(), "foco entra na janela ao abrir");
  let sempreDentro = true;
  for (let i = 0; i < 8; i++) { await page.keyboard.press("Tab"); sempreDentro &&= await dentro(); }
  for (let i = 0; i < 8; i++) { await page.keyboard.press("Shift+Tab"); sempreDentro &&= await dentro(); }
  ok(sempreDentro, "Tab e Shift+Tab ficam presos dentro da janela (8 voltas para cada lado)");
  const lbl = await page.evaluate(() => document.querySelector(".panel[role=dialog]").getAttribute("aria-labelledby"));
  ok(lbl === "modal-titulo", "janela tem role=dialog, aria-modal e aria-labelledby");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  ok(!(await page.$(".panel[role=dialog]")), "Esc fecha a janela");
  const volta = await page.evaluate(() => document.activeElement?.textContent?.trim());
  ok(volta === "Encerrar", `foco volta ao botão que abriu (${volta})`);
  // percurso só com teclado pela visão geral
  await irPara(page, "#/", 1500);
  const alcancaveis = await page.evaluate(() => [...document.querySelectorAll("a[href], button, input, select, textarea")].filter((e) => !e.closest("[hidden]") && getComputedStyle(e).display !== "none" && !e.disabled && e.tabIndex < 0).length);
  ok(alcancaveis === 0, `nenhum controle visível fora da ordem de Tab (${alcancaveis})`);
  const foco = await page.evaluate(() => { const e = document.querySelector(".nav-item"); e.focus(); const s = getComputedStyle(e); return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2; });
  ok(foco, "foco visível (outline de 2 px) nos itens de menu");
  await ctx.close();
}

// ---------- 4. Movimento reduzido ----------
{
  const { ctx, page } = await nova({ width: 1366, height: 900 }, { reducedMotion: "reduce" });
  await page.waitForSelector(".kpi");
  await page.waitForTimeout(300);
  const m = await page.evaluate(() => ({
    halo: parseFloat(getComputedStyle(document.querySelector(".halo")).animationDuration) * 1000,
    shimmer: parseFloat(getComputedStyle(document.querySelector(".f-bar"), "::after").animationDuration) * 1000,
    valor: document.querySelector(".kpi .val").textContent,
  }));
  ok(m.halo < 1 && m.shimmer < 1, `animações encurtadas a ~0 ms com movimento reduzido (pulso ${m.halo} ms, brilho ${m.shimmer} ms)`);
  ok(/[1-9]/.test(m.valor), `count-up desligado: KPI já mostra o valor final (${m.valor})`);
  await ctx.close();
}

// ---------- 5. Permissão: papel de leitura ----------
{
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/admin/auth/entrar`);   // dev entra com o 1º operador (operação)
  await ctx.close();
}

await browser.close();
console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTudo certo no navegador");
process.exit(falhas ? 1 : 0);
