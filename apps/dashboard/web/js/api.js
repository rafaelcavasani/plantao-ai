// Cliente da API de operação (/admin/*). Usa o cookie de sessão (HttpOnly) e nunca guarda segredo no navegador.
// Erros viram `ErroApi` com o `codigo`, a `mensagem` e os `campos` do contrato (contracts/admin-api.md).

import { emitir } from "./dom.js";

export class ErroApi extends Error {
  constructor(status, corpo) {
    super(corpo?.mensagem ?? `Erro ${status}`);
    this.status = status;
    this.codigo = corpo?.codigo ?? (status === 0 ? "sem_rede" : "erro");
    this.mensagem = corpo?.mensagem ?? "Não foi possível concluir a operação.";
    this.campos = corpo?.campos ?? null;
    this.corpo = corpo ?? null;
  }
}

function montarUrl(caminho, params) {
  const url = new URL(caminho, window.location.origin);
  for (const [chave, valor] of Object.entries(params ?? {})) {
    if (valor !== null && valor !== undefined && valor !== "") url.searchParams.set(chave, String(valor));
  }
  return url;
}

async function pedir(metodo, caminho, { params, corpo, bruto = false } = {}) {
  const headers = { Accept: bruto ? "*/*" : "application/json" };
  const opcoes = { method: metodo, headers, credentials: "same-origin" };
  if (corpo !== undefined) {
    headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  let resposta;
  try {
    resposta = await fetch(montarUrl(caminho, params), opcoes);
  } catch {
    throw new ErroApi(0, { codigo: "sem_rede", mensagem: "Sem conexão com o servidor. Tente de novo." });
  }
  if (resposta.status === 204) return null;
  if (resposta.ok) return bruto ? resposta.blob() : resposta.json();
  let dados = null;
  try {
    dados = await resposta.json();
  } catch {
    dados = null;
  }
  if (resposta.status === 401) emitir("sessao-expirada");
  throw new ErroApi(resposta.status, dados);
}

export const api = {
  get: (caminho, params) => pedir("GET", caminho, { params }),
  post: (caminho, corpo) => pedir("POST", caminho, { corpo: corpo ?? {} }),
  patch: (caminho, corpo) => pedir("PATCH", caminho, { corpo }),
  put: (caminho, corpo) => pedir("PUT", caminho, { corpo }),
  arquivo: (caminho, params) => pedir("GET", caminho, { params, bruto: true }),
};

/** Baixa um arquivo gerado pelo servidor sem usar HTML nem script inline. */
export async function baixar(caminho, params, nome) {
  const blob = await api.arquivo(caminho, params);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  a.click();
  URL.revokeObjectURL(url);
}

export const caminhos = {
  eu: "/admin/eu",
  sair: "/admin/auth/sair",
  entrar: "/admin/auth/entrar",
  saude: "/admin/saude",
  atualizar: "/admin/atualizar",
  visaoGeral: "/admin/visao-geral",
  empresas: "/admin/empresas",
  empresasCsv: "/admin/empresas.csv",
  planos: "/admin/planos",
  empresa: (slug) => `/admin/empresas/${encodeURIComponent(slug)}`,
  serie: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/serie`,
  configuracao: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/configuracao`,
  auditoria: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/auditoria`,
  conversas: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/conversas`,
  conversa: (slug, id) => `/admin/empresas/${encodeURIComponent(slug)}/conversas/${encodeURIComponent(id)}`,
  estado: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/estado`,
  prontidao: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/prontidao`,
  conexao: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/conexao`,
  documentos: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/documentos`,
  remessa: (slug, id) => `/admin/empresas/${encodeURIComponent(slug)}/documentos/remessas/${encodeURIComponent(id)}`,
  apagarResumo: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/apagar-dados/resumo`,
  apagar: (slug) => `/admin/empresas/${encodeURIComponent(slug)}/apagar-dados`,
};
