// Estados do funil na ordem em que um produto os percorre, com a leitura em português.
export const STATES: { key: string; label: string; tone: "neutral" | "info" | "good" | "bad" | "warn" }[] = [
  { key: "DISCOVERY", label: "Descoberto", tone: "neutral" },
  { key: "QUALIFICATION", label: "Qualificado", tone: "info" },
  { key: "CANDIDATE", label: "Candidato", tone: "info" },
  { key: "TEST", label: "Em teste", tone: "warn" },
  { key: "ACTIVE", label: "Ativo", tone: "good" },
  { key: "WINNER", label: "Vencedor", tone: "good" },
  { key: "PAUSED", label: "Pausado", tone: "warn" },
  { key: "UNDER_REVIEW", label: "Em revisão", tone: "warn" },
  { key: "REJECTED", label: "Rejeitado", tone: "bad" },
  { key: "REPLACED", label: "Substituído", tone: "bad" },
  { key: "EXPIRED", label: "Expirado", tone: "neutral" },
];

export const stateLabel = (key: string) => STATES.find((s) => s.key === key)?.label ?? key;

// Por que o produto está onde está. Os códigos vêm do backend (`reason_code`).
const REASONS: Record<string, string> = {
  DISCOVERED: "Encontrado na busca",
  PASSED_HARD_FILTERS: "Passou nos filtros",
  OUT_OF_STOCK: "Sem estoque",
  PRICE_TOO_LOW: "Preço abaixo do mínimo",
  COMMISSION_TOO_LOW: "Comissão abaixo do mínimo",
  LOW_RATING: "Nota baixa",
  OPPORTUNITY_SCORE_ABOVE_THRESHOLD: "Score acima do corte",
  PORTFOLIO_ENTRY: "Entrou no portfólio",
  REPLACEMENT_ENTRY: "Entrou no lugar de outro",
  GRADUATED_FROM_TEST: "Saiu do teste com bom resultado",
};

export function reasonLabel(code: string | null): string | null {
  if (!code) return null;
  if (code.startsWith("REPLACED_")) return "Substituído por desempenho";
  return REASONS[code] ?? code;
}

export const COMPONENTS: Record<string, string> = {
  demand: "Demanda (vendas)",
  commission: "Comissão em R$",
  social_proof: "Prova social (nota)",
  availability: "Disponibilidade (estoque)",
};

export const FIELDS: Record<string, string> = {
  price: "preço",
  commission_rate: "comissão",
  rating: "nota",
  rating_count: "nº de avaliações",
  sales_volume: "vendas",
  stock: "estoque",
  original_price: "preço original",
  demand: "demanda",
  commission: "comissão",
  social_proof: "prova social",
  availability: "disponibilidade",
};
