// Gráficos em SVG puro (research R-02). A matemática fica em funções puras (testadas com `node --test`);
// o desenho usa `dom.js`, sem estilo inline.

import { h, s } from "./dom.js";

// --- Matemática (pura) ---------------------------------------------------------------------------

/** Menor "número bonito" (1, 1,5, 2, 2,5, 3, 4, 5, 6, 8 x 10^k) que cobre `maximo` em `divisoes` intervalos. */
export function escalaDoEixo(maximo, divisoes = 4) {
  if (!(maximo > 0)) return { passo: 1, topo: divisoes, divisoes };
  const bruto = maximo / divisoes;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * potencia).find((p) => p >= bruto - 1e-12);
  return { passo, topo: passo * divisoes, divisoes };
}

export function rotuloDoEixo(valor) {
  if (valor >= 1_000_000) return `${+(valor / 1_000_000).toFixed(1)}M`;
  if (valor >= 1000) return `${+(valor / 1000).toFixed(1)}k`.replace(".", ",");
  return String(+valor.toFixed(2)).replace(".", ",");
}

/** Um arco por segmento sobre a MESMA circunferência: `dasharray = (fração x C) C`, `dashoffset = -(soma anterior x C)`. */
export function arcosDoDonut(valores, raio) {
  const circunferencia = 2 * Math.PI * raio;
  const total = valores.reduce((a, v) => a + v, 0);
  let acumulado = 0;
  return valores.map((valor) => {
    const fracao = total > 0 ? valor / total : 0;
    const arco = { fracao, comprimento: fracao * circunferencia, deslocamento: -(acumulado * circunferencia), circunferencia };
    acumulado += fracao;
    return arco;
  });
}

/** Larguras RELATIVAS por posição no funil (não proporcionais aos valores): de 100% a 30%, nunca abaixo de 20%. */
export function largurasDoFunil(etapas) {
  if (etapas <= 1) return [100];
  const queda = 70 / (etapas - 1);
  return Array.from({ length: etapas }, (_, i) => Math.max(20, Math.round((100 - i * queda) * 10) / 10));
}

/** Curva suave sem estourar entre pontos (tangentes horizontais no ponto médio). */
export function caminhoSuave(pontos) {
  if (pontos.length === 0) return "";
  return pontos
    .map(([x, y], i) => {
      if (i === 0) return `M${x} ${y}`;
      const [xa, ya] = pontos[i - 1];
      const mx = (xa + x) / 2;
      return `C${mx} ${ya} ${mx} ${y} ${x} ${y}`;
    })
    .join(" ");
}

export function geometria(largura = 760, altura = 300) {
  return { largura, altura, pad: { l: 52, r: 22, t: 14, b: 30 } };
}

// --- Desenho ---------------------------------------------------------------------------------------

const easeOut = (t) => 1 - (1 - t) ** 4;

/**
 * Gráfico de linhas com área, grade e dica no hover. `series`: [{nome, valores, cor, tracejada}].
 * O último ponto de cada série tem uma marca com `cx`/`cy` FIXOS que só pulsa em escala e opacidade
 * (nenhuma animação de posição); trocar o período redesenha e reposiciona a marca na hora.
 */
export function linha(container, { rotulos, series, formatarValor = (v) => String(v), animar = false, idGrafico = "g" }) {
  const { largura, altura, pad } = geometria();
  const n = rotulos.length;
  const maximo = Math.max(0, ...series.flatMap((x) => x.valores));
  const eixo = escalaDoEixo(maximo);
  const x = (i) => (n > 1 ? pad.l + (i * (largura - pad.l - pad.r)) / (n - 1) : pad.l);
  const y = (v) => pad.t + (1 - v / eixo.topo) * (altura - pad.t - pad.b);
  const base = altura - pad.b;

  const svg = s("svg", { class: "chart", viewBox: `0 0 ${largura} ${altura}`, role: "img",
    "aria-label": `Gráfico de ${series.map((x) => x.nome).join(" e ")} por período` });
  const defs = s("defs");
  const clip = s("clipPath", { id: `${idGrafico}-revela` }, s("rect", { x: 0, y: 0, width: animar ? 0 : largura, height: altura }));
  defs.append(clip);
  series.forEach((serie, i) => {
    defs.append(
      s("linearGradient", { id: `${idGrafico}-g${i}`, x1: 0, y1: 0, x2: 0, y2: 1 },
        s("stop", { offset: 0, "stop-color": serie.cor, "stop-opacity": i === 0 ? 0.38 : 0.16 }),
        s("stop", { offset: 1, "stop-color": serie.cor, "stop-opacity": 0 })),
    );
  });
  svg.append(defs);

  const grade = s("g");
  for (let k = 0; k <= eixo.divisoes; k++) {
    const v = eixo.passo * k;
    grade.append(s("line", { x1: pad.l, x2: largura - pad.r, y1: y(v), y2: y(v), stroke: "rgb(255 255 255 / .06)" }));
    grade.append(s("text", { x: pad.l - 10, y: y(v) + 4, "text-anchor": "end" }, rotuloDoEixo(v)));
  }
  const passoRotulo = n > 8 ? 2 : 1;
  rotulos.forEach((r, i) => {
    if (i % passoRotulo && i !== n - 1) return;
    if (i === n - 2 && passoRotulo > 1) return; // o penúltimo colaria no último rótulo
    grade.append(s("text", { x: x(i), y: altura - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" }, r));
  });
  svg.append(grade);

  const desenho = s("g", { "clip-path": `url(#${idGrafico}-revela)` });
  [...series].reverse().forEach((serie, ri) => {
    const i = series.length - 1 - ri;
    const pontos = serie.valores.map((v, k) => [x(k), y(v)]);
    const caminho = caminhoSuave(pontos);
    if (!pontos.length) return;
    desenho.append(s("path", { d: `${caminho} L${x(n - 1)} ${base} L${x(0)} ${base} Z`, fill: `url(#${idGrafico}-g${i})` }));
    desenho.append(s("path", { d: caminho, fill: "none", stroke: serie.cor, "stroke-width": i === 0 ? 2.5 : 2,
      "stroke-linecap": "round", "stroke-dasharray": serie.tracejada ? "6 6" : null }));
  });
  svg.append(desenho);

  const marcas = s("g", { class: animar ? "marcas oculta" : "marcas" });
  series.forEach((serie, i) => {
    if (!serie.valores.length) return;
    const cx = x(n - 1);
    const cy = y(serie.valores[n - 1]);
    marcas.append(s("circle", { class: "end-dot halo", cx, cy, r: 4, fill: serie.cor, "data-atraso": i ? "2" : "1" }));
    marcas.append(s("circle", { cx, cy, r: 4, fill: serie.cor, stroke: "#0a0a0d", "stroke-width": 2 }));
  });
  svg.append(marcas);

  const guia = s("line", { y1: pad.t, y2: base, stroke: "rgb(255 255 255 / .18)", "stroke-dasharray": "3 4", opacity: 0 });
  const alvo = s("rect", { x: pad.l, y: 0, width: largura - pad.l - pad.r, height: altura, fill: "transparent" });
  svg.append(guia, alvo);

  const dica = h("div", { class: "tip", role: "status" });
  container.replaceChildren(svg, dica);

  alvo.addEventListener("mousemove", (e) => {
    const caixa = svg.getBoundingClientRect();
    const k = caixa.width / largura;
    const passo = n > 1 ? (largura - pad.l - pad.r) / (n - 1) : 1;
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - caixa.left) / k - pad.l) / passo)));
    guia.setAttribute("x1", x(i));
    guia.setAttribute("x2", x(i));
    guia.setAttribute("opacity", 1);
    dica.replaceChildren(
      h("b", null, rotulos[i]),
      ...series.map((serie) =>
        h("div", null, h("span", null, h("i", { class: "dot", "data-cor": serie.cor }), ` ${serie.nome}`),
          h("span", { class: "num" }, formatarValor(serie.valores[i]))),
      ),
    );
    dica.querySelectorAll(".dot").forEach((d) => { d.style.background = d.dataset.cor; });
    const esquerda = Math.min(container.clientWidth - dica.offsetWidth - 4, Math.max(4, x(i) * k + 14));
    dica.style.transform = `translate(${esquerda}px, ${Math.max(0, y(series[0].valores[i]) * k - 10)}px)`;
    dica.style.opacity = 1;
  });
  alvo.addEventListener("mouseleave", () => {
    dica.style.opacity = 0;
    guia.setAttribute("opacity", 0);
  });

  if (animar) {
    const rect = clip.firstChild;
    const inicio = performance.now();
    const passo = () => {
      const t = Math.min(1, (performance.now() - inicio) / 1400);
      rect.setAttribute("width", largura * easeOut(t));
      if (t < 1) requestAnimationFrame(passo);
      else marcas.classList.remove("oculta");
    };
    requestAnimationFrame(passo);
  }
  return svg;
}

/** Donut: um `<circle>` por segmento, todos sobre a mesma circunferência. `itens`: [{nome, valor, cor}]. */
export function donut(container, itens, { aoPassar } = {}) {
  const raio = 70;
  const arcos = arcosDoDonut(itens.map((i) => i.valor), raio);
  const svg = s("svg", { viewBox: "0 0 200 200", role: "img", class: "donut-svg",
    "aria-label": `Distribuição: ${itens.map((i) => `${i.nome} ${i.valor}`).join(", ")}` });
  svg.append(s("circle", { cx: 100, cy: 100, r: raio, fill: "none", stroke: "rgb(255 255 255 / .05)", "stroke-width": 22 }));
  const segmentos = itens.map((item, i) => {
    const seg = s("circle", { class: "seg", cx: 100, cy: 100, r: raio, stroke: item.cor,
      "stroke-dasharray": `0 ${arcos[i].circunferencia}`, "stroke-dashoffset": arcos[i].deslocamento });
    seg.addEventListener("mouseenter", () => aoPassar?.(item));
    seg.addEventListener("mouseleave", () => aoPassar?.(null));
    svg.append(seg);
    return seg;
  });
  container.replaceChildren(svg);
  requestAnimationFrame(() =>
    requestAnimationFrame(() =>
      segmentos.forEach((seg, i) => seg.setAttribute("stroke-dasharray", `${arcos[i].comprimento} ${arcos[i].circunferencia}`)),
    ),
  );
  return svg;
}

/** Funil horizontal com escala RELATIVA por etapa. `etapas`: [{nome, texto}], `conversoes`: textos entre as etapas. */
export function funil(container, etapas, conversoes) {
  const larguras = largurasDoFunil(etapas.length);
  const linhas = [];
  etapas.forEach((etapa, i) => {
    const barra = h("div", { class: "f-bar" });
    linhas.push(h("div", { class: "f-row" },
      h("span", { class: "name" }, etapa.nome),
      h("div", { class: "f-track" }, barra),
      h("span", { class: "amt num" }, etapa.texto)));
    barra.dataset.largura = String(larguras[i]);
    if (conversoes[i]) {
      linhas.push(h("div", { class: "f-conv" }, h("span", null, h("i", { class: "fa-solid fa-arrow-down", "aria-hidden": "true" }), conversoes[i])));
    }
  });
  container.replaceChildren(...linhas);
  setTimeout(() => container.querySelectorAll(".f-bar").forEach((b, i) =>
    setTimeout(() => { b.style.width = `${b.dataset.largura}%`; }, i * 140)), 300);
}

/** Sparkline de um KPI. `tom`: ok | warn | crit. */
export function sparkline(valores, tom = "ok") {
  const largura = 200;
  const altura = 36;
  const cor = tom === "warn" ? "#f5b942" : tom === "crit" ? "#f87171" : "#2dd4bf";
  const minimo = Math.min(...valores);
  const faixa = Math.max(...valores) - minimo || 1;
  const pontos = valores.map((v, i) => [(i * largura) / Math.max(valores.length - 1, 1), altura - 3 - ((v - minimo) / faixa) * (altura - 8)]);
  const caminho = pontos.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  const id = `sp${Math.random().toString(36).slice(2, 8)}`;
  return s("svg", { class: "spark", viewBox: `0 0 ${largura} ${altura}`, preserveAspectRatio: "none", "aria-hidden": "true" },
    s("defs", null, s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
      s("stop", { offset: 0, "stop-color": cor, "stop-opacity": 0.25 }), s("stop", { offset: 1, "stop-color": cor, "stop-opacity": 0 }))),
    s("path", { d: `${caminho} L${largura} ${altura} L0 ${altura} Z`, fill: `url(#${id})` }),
    s("path", { d: caminho, fill: "none", stroke: cor, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke",
      "stroke-linejoin": "round", "stroke-linecap": "round" }));
}

/** Anima um número de `de` até `para` (count-up). Sem animação com `prefers-reduced-motion`. */
export function contar(el, de, para, formatar, duracao = 1100) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || de === para) {
    el.textContent = formatar(para);
    return;
  }
  const inicio = performance.now();
  const passo = () => {
    const t = Math.min(1, (performance.now() - inicio) / duracao);
    el.textContent = formatar(de + (para - de) * easeOut(t));
    if (t < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}
