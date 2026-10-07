// Formatação para a tela: números em pt-BR, moeda em US$ e datas no fuso de São Paulo.

export const FUSO = "America/Sao_Paulo";

const fmtNumero = (casas) =>
  new Intl.NumberFormat("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const FORMATOS = { 0: fmtNumero(0), 1: fmtNumero(1), 2: fmtNumero(2), 4: fmtNumero(4) };

export const SEM_DADO = "—";

export function inteiro(valor) {
  return valor === null || valor === undefined ? SEM_DADO : FORMATOS[0].format(Math.round(valor));
}

export function decimal(valor, casas = 1) {
  if (valor === null || valor === undefined) return SEM_DADO;
  return (FORMATOS[casas] ?? fmtNumero(casas)).format(valor);
}

export function usd(valor, casas = 2) {
  return valor === null || valor === undefined ? SEM_DADO : `US$ ${decimal(valor, casas)}`;
}

export function pct(valor, casas = 1) {
  return valor === null || valor === undefined ? SEM_DADO : `${decimal(valor, casas)}%`;
}

/** Variação com sinal tipográfico: "+12,4%", "−8,2%". */
export function variacaoPct(atual, anterior) {
  if (!anterior) return null;
  const d = ((atual - anterior) / anterior) * 100;
  return { valor: d, texto: `${d >= 0 ? "+" : "−"}${decimal(Math.abs(d), 1)}%` };
}

export function variacaoPontos(atual, anterior) {
  const d = atual - anterior;
  return { valor: d, texto: `${d >= 0 ? "+" : "−"}${decimal(Math.abs(d), 1)} pts` };
}

/** "há 3 min", "há 26 h", "há 3 dias" ou "agora". */
export function relativo(iso, agora = Date.now()) {
  if (!iso) return SEM_DADO;
  const minutos = Math.max(0, Math.floor((agora - new Date(iso).getTime()) / 60000));
  if (minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 48) return `há ${horas} h`;
  return `há ${Math.floor(horas / 24)} dias`;
}

const dataHoraFmt = new Intl.DateTimeFormat("pt-BR", {
  timeZone: FUSO, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const dataFmt = new Intl.DateTimeFormat("pt-BR", {
  timeZone: FUSO, day: "2-digit", month: "2-digit", year: "numeric",
});
const diaCurtoFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, day: "2-digit", month: "short" });
const horaFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit" });

export const dataHora = (iso) => (iso ? dataHoraFmt.format(new Date(iso)) : SEM_DADO);
export const data = (iso) => (iso ? dataFmt.format(new Date(iso)) : SEM_DADO);
export const diaCurto = (iso) => (iso ? diaCurtoFmt.format(new Date(iso)).replace(".", "") : "");
export const hora = (iso) => (iso ? horaFmt.format(new Date(iso)) : "");

export const REMETENTE = { lead: "contato", agente: "agente", humano: "atendente" };

/** "há 3 min" mais quem enviou; "sem mensagens" quando a empresa nunca recebeu nenhuma. */
export function ultimaMensagem(ultima, agora = Date.now()) {
  if (!ultima) return { quando: "sem mensagens", quem: null };
  return { quando: relativo(ultima.em, agora), quem: REMETENTE[ultima.remetente] ?? ultima.remetente };
}

export const ESTADOS = {
  ativo: "Ativo",
  em_configuracao: "Em configuração",
  suspenso: "Suspenso",
  encerrado: "Encerrado",
};

export const CLASSE_DO_ESTADO = {
  ativo: "b-ativa",
  em_configuracao: "b-aprend",
  suspenso: "b-susp",
  encerrado: "b-pausada",
};

export const PERIODOS = { hoje: "Hoje", "7d": "7d", "30d": "30d" };
export const COMPARACAO = { hoje: "vs ontem", "7d": "vs 7d anterior", "30d": "vs 30d anterior" };
