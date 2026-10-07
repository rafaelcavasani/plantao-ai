// Apresentação dos motivos de atenção (a regra de quando alertar é do servidor: core/painel/atencao.py).
// Cor nunca é o único sinal: todo motivo tem ícone e texto (FR-032).

export const MOTIVOS = {
  conexao_nao_verificada: { icone: "link-slash", rotulo: "Conexão do canal" },
  custo_alto: { icone: "coins", rotulo: "Custo alto" },
  sem_atividade: { icone: "moon", rotulo: "Sem atividade" },
  handoff_alto: { icone: "hand", rotulo: "Handoff alto" },
  falhas_envio: { icone: "triangle-exclamation", rotulo: "Falhas de envio" },
};

const PADRAO = { icone: "triangle-exclamation", rotulo: "Atenção" };

export const visual = (codigo) => MOTIVOS[codigo] ?? PADRAO;

const ORDEM = { critica: 0, aviso: 1 };

/** Mais grave primeiro; empate por nome. */
export function ordenarPorGravidade(alertas) {
  return [...alertas].sort(
    (a, b) =>
      (ORDEM[a.gravidade] ?? 9) - (ORDEM[b.gravidade] ?? 9) ||
      String(a.nome ?? "").localeCompare(String(b.nome ?? ""), "pt-BR"),
  );
}

/** Texto alternativo de uma empresa com atenção, a partir da lista da API. */
export function descricao(atencao) {
  return (atencao ?? []).map((a) => a.detalhe).join("; ");
}

export const gravidadeMaxima = (atencao) =>
  (atencao ?? []).some((a) => a.gravidade === "critica") ? "critica" : (atencao ?? []).length ? "aviso" : null;
