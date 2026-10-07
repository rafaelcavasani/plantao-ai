// Estado compartilhado da interface: quem está logado e o período escolhido. Só preferências de visualização
// vão para o `localStorage` (nunca segredo nem dado de empresa), e a tela funciona sem ele.

const CHAVE_PERIODO = "painel:periodo";
const CHAVE_MENU = "painel:menu-recolhido";

function ler(chave) {
  try {
    return window.localStorage.getItem(chave);
  } catch {
    return null;
  }
}

function gravar(chave, valor) {
  try {
    window.localStorage.setItem(chave, valor);
  } catch {
    /* modo privado ou armazenamento bloqueado: segue sem lembrar */
  }
}

const PERIODOS_VALIDOS = ["hoje", "7d", "30d"];
const salvo = ler(CHAVE_PERIODO);

const estado = {
  operador: null, // { email, papel, expira_em }
  periodo: PERIODOS_VALIDOS.includes(salvo) ? salvo : "30d",
};

const ouvintes = new Set();

export const obter = () => estado;

export function definir(parcial) {
  Object.assign(estado, parcial);
  if (parcial.periodo) gravar(CHAVE_PERIODO, parcial.periodo);
  ouvintes.forEach((fn) => fn(estado));
}

export function assinar(fn) {
  ouvintes.add(fn);
  return () => ouvintes.delete(fn);
}

export const podeOperar = () => estado.operador?.papel === "operacao";

export const menuRecolhidoSalvo = () => {
  const v = ler(CHAVE_MENU);
  return v === null ? null : v === "1";
};
export const lembrarMenu = (recolhido) => gravar(CHAVE_MENU, recolhido ? "1" : "0");
