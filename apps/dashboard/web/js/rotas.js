// Rotas por hash (contracts/painel-ui.md). Função pura: `resolverRota(hash)` não toca no DOM nem na API.

export const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function resolverRota(hash) {
  const bruto = String(hash ?? "").replace(/^#\/?/, "").replace(/\/+$/, "");
  const partes = bruto === "" ? [] : bruto.split("/");
  let p;
  try {
    p = partes.map(decodeURIComponent);
  } catch {
    return { tela: "nao-encontrada" };
  }
  const slugOk = (s) => typeof s === "string" && s.length <= 63 && SLUG_RE.test(s);

  if (p.length === 0) return { tela: "visao-geral" };
  if (p[0] === "empresas") {
    if (p.length === 1) return { tela: "empresas" };
    if (p.length === 2 && p[1] === "nova") return { tela: "formulario", modo: "nova" };
    return { tela: "nao-encontrada" };
  }
  if (p[0] === "empresa" && slugOk(p[1])) {
    if (p.length === 2) return { tela: "ficha", slug: p[1] };
    if (p.length === 3 && p[2] === "editar") return { tela: "formulario", modo: "editar", slug: p[1] };
    if (p.length === 3 && p[2] === "conversas") return { tela: "conversas", slug: p[1] };
    if (p.length === 4 && p[2] === "conversas" && UUID_RE.test(p[3])) {
      return { tela: "conversa", slug: p[1], id: p[3] };
    }
  }
  return { tela: "nao-encontrada" };
}

export const ir = (destino) => {
  window.location.hash = destino;
};

export const hrefs = {
  visaoGeral: "#/",
  empresas: "#/empresas",
  nova: "#/empresas/nova",
  ficha: (slug) => `#/empresa/${encodeURIComponent(slug)}`,
  editar: (slug) => `#/empresa/${encodeURIComponent(slug)}/editar`,
  conversas: (slug) => `#/empresa/${encodeURIComponent(slug)}/conversas`,
  conversa: (slug, id) => `#/empresa/${encodeURIComponent(slug)}/conversas/${encodeURIComponent(id)}`,
};
