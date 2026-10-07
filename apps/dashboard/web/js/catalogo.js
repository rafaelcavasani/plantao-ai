// Catálogo de planos (nome, orçamento e preço). Buscado uma vez e reaproveitado pelas telas.

import { api, caminhos } from "./api.js";

let promessa = null;

export function planos() {
  promessa ??= api.get(caminhos.planos).catch((erro) => {
    promessa = null; // tenta de novo na próxima vez
    throw erro;
  });
  return promessa;
}

export async function nomesDosPlanos() {
  try {
    return Object.fromEntries((await planos()).map((p) => [p.chave, p.nome]));
  } catch {
    return {};
  }
}

export const NICHOS_SUGERIDOS = [
  "Clínica odontológica",
  "Clínica de saúde",
  "Academia",
  "Imobiliária",
  "Pet shop",
  "Escola de idiomas",
  "Barbearia",
  "Ótica",
  "Contabilidade",
];
