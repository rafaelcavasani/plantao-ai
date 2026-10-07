// Validação do formulário de empresa. As mesmas regras do servidor (contracts/admin-api.md, core/tenancy/config.py):
// o servidor sempre repete a validação, e os erros dele aparecem no mesmo campo. Funções puras, sem DOM.

export const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
export const SLUG_MIN = 3;
export const SLUG_MAX = 63;
export const SEGREDO_MIN = 32;
export const HORARIO_RE = /^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$/;
export const FECHADO = "fechado";

export const DIAS = [
  ["seg", "Segunda"],
  ["ter", "Terça"],
  ["qua", "Quarta"],
  ["qui", "Quinta"],
  ["sex", "Sexta"],
  ["sab", "Sábado"],
  ["dom", "Domingo"],
];

/** Faixas aceitas pelo servidor (`ConfigEmpresa`). */
export const FAIXAS = {
  limite_desconto_percentual: { min: 0, max: 100, rotulo: "Informe de 0 a 100." },
  confianca_minima_handoff: { min: 0, max: 1, rotulo: "Informe de 0 a 1." },
  limite_mensagens_por_minuto: { min: 1, max: 6000, inteiro: true, rotulo: "Informe um inteiro de 1 a 6000." },
  handoff_ttl_minutos: { min: 1, max: 1440, inteiro: true, rotulo: "Informe um inteiro de 1 a 1440." },
};

export const TAMANHO_MAXIMO_ARQUIVO = 2 * 1024 * 1024;
export const MAXIMO_DE_ARQUIVOS = 10;
export const EXTENSOES_ACEITAS = [".md", ".txt", ".pdf"];

/** Sugestão de slug a partir do nome: minúsculas, sem acento, hífen entre palavras, até 63 caracteres. */
export function slugificar(nome) {
  return String(nome ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, SLUG_MAX)
    .replace(/-+$/g, "");
}

export function validarSlug(slug) {
  if (!slug) return "Informe o slug.";
  if (slug.length < SLUG_MIN || slug.length > SLUG_MAX || !SLUG_RE.test(slug)) {
    return `Use só minúsculas, números e hífen, de ${SLUG_MIN} a ${SLUG_MAX} caracteres.`;
  }
  return null;
}

/** `HH:MM-HH:MM` ou "fechado" (sem diferenciar maiúsculas). Vazio também vale: dia sem atendimento. */
export function validarHorario(valor) {
  const v = String(valor ?? "").trim().toLowerCase();
  if (v === "" || v === FECHADO) return null;
  return HORARIO_RE.test(v) ? null : `Use HH:MM-HH:MM ou "${FECHADO}".`;
}

export function validarFaixa(campo, valor) {
  const f = FAIXAS[campo];
  const texto = String(valor ?? "").trim();
  if (texto === "") return f.rotulo;
  const n = Number(texto.replace(",", "."));
  if (!Number.isFinite(n) || n < f.min || n > f.max || (f.inteiro && !Number.isInteger(n))) return f.rotulo;
  return null;
}

export function validarSegredo(segredo) {
  return segredo.length >= SEGREDO_MIN
    ? null
    : `O segredo de entrega precisa ter pelo menos ${SEGREDO_MIN} caracteres.`;
}

/**
 * Valida o formulário inteiro e devolve `{campo: mensagem}` na mesma chave que a API usa em `campos`.
 * `valores`: nome, slug, nicho, plano, tom_de_voz, horario {dia: texto}, e os números como texto, mais
 * `conexao` ({instancia, segredo_entrega, chave_envio}) quando o bloco de conexão está aberto.
 * `contexto`: `{modo, slugsExistentes, instanciasEmUso}`.
 */
export function validarFormulario(valores, contexto = {}) {
  const erros = {};
  const nome = String(valores.nome ?? "").trim();
  if (nome.length < 2) erros.nome = "Informe o nome da empresa.";
  if (nome.length > 255) erros.nome = "O nome tem no máximo 255 caracteres.";

  if (contexto.modo !== "editar") {
    const e = validarSlug(String(valores.slug ?? ""));
    if (e) erros.slug = e;
    else if ((contexto.slugsExistentes ?? []).includes(valores.slug)) {
      erros.slug = `Já existe uma empresa com o slug '${valores.slug}'.`;
    }
  }
  if (!String(valores.nicho ?? "").trim()) erros.nicho = "Informe o nicho.";
  if (!String(valores.tom_de_voz ?? "").trim()) erros["configuracao.tom_de_voz"] = "Descreva o tom de voz.";

  for (const [dia, rotulo] of DIAS) {
    const e = validarHorario(valores.horario?.[dia]);
    if (e) {
      erros["configuracao.horario_funcionamento"] = `${rotulo}: ${e}`;
      break;
    }
  }
  for (const campo of Object.keys(FAIXAS)) {
    const e = validarFaixa(campo, valores[campo]);
    if (e) erros[`configuracao.${campo}`] = e;
  }

  const conexao = valores.conexao;
  if (conexao) {
    const instancia = String(conexao.instancia ?? "").trim();
    if (!instancia) erros["conexao.instancia"] = "Informe a instância.";
    else if ((contexto.instanciasEmUso ?? []).includes(instancia)) {
      erros["conexao.instancia"] = `A instância '${instancia}' já está em uso por outra empresa.`;
    }
    const segredo = validarSegredo(String(conexao.segredo_entrega ?? ""));
    if (segredo) erros["conexao.segredo_entrega"] = segredo;
    if (!String(conexao.chave_envio ?? "")) erros["conexao.chave_envio"] = "A chave de envio está vazia.";
  }
  return erros;
}

/** Primeiro campo com erro, na ordem em que aparecem no formulário (para levar o foco até ele). */
export const ORDEM_DOS_CAMPOS = [
  "nome",
  "slug",
  "nicho",
  "plano",
  "configuracao.tom_de_voz",
  "configuracao.horario_funcionamento",
  "configuracao.limite_desconto_percentual",
  "configuracao.confianca_minima_handoff",
  "configuracao.limite_mensagens_por_minuto",
  "configuracao.handoff_ttl_minutos",
  "conexao.instancia",
  "conexao.segredo_entrega",
  "conexao.chave_envio",
];

export function primeiroCampoComErro(erros) {
  return ORDEM_DOS_CAMPOS.find((c) => c in erros) ?? Object.keys(erros)[0] ?? null;
}

/** Valida a lista de arquivos escolhidos; devolve `{aceitos, recusados:[{nome, motivo}]}` (nomes repetidos incluídos). */
export function triarArquivos(arquivos, jaEscolhidos = []) {
  const aceitos = [];
  const recusados = [];
  const nomes = new Set(jaEscolhidos.map((a) => a.name));
  for (const arq of arquivos) {
    const ponto = arq.name.lastIndexOf(".");
    const ext = ponto >= 0 ? arq.name.slice(ponto).toLowerCase() : "";
    if (!EXTENSOES_ACEITAS.includes(ext)) recusados.push({ nome: arq.name, motivo: "formato não suportado" });
    else if (arq.size > TAMANHO_MAXIMO_ARQUIVO) recusados.push({ nome: arq.name, motivo: "acima de 2 MB" });
    else if (nomes.has(arq.name)) recusados.push({ nome: arq.name, motivo: "nome repetido na remessa" });
    else if (jaEscolhidos.length + aceitos.length >= MAXIMO_DE_ARQUIVOS) {
      recusados.push({ nome: arq.name, motivo: `no máximo ${MAXIMO_DE_ARQUIVOS} arquivos por remessa` });
    } else {
      aceitos.push(arq);
      nomes.add(arq.name);
    }
  }
  return { aceitos, recusados };
}

/** Texto de confirmação de encerramento: só vale se for exatamente o nome da empresa. */
export const nomeConfere = (digitado, nome) => digitado === nome;
