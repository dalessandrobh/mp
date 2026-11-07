// Cliente HTTP do dashboard.
//
// A base é relativa de propósito: em produção o Traefik serve o front em / e o
// backend em /api no MESMO host, então não há origem cruzada nem CORS. No dev
// o Vite faz o mesmo desvio (ver vite.config.ts).
import { getAccessToken, signOut } from "./auth";

const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Accept: "application/json",
      ...(body !== undefined && { "Content-Type": "application/json" }),
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });

  if (response.status === 401 && token) {
    // Token recusado pelo backend: a sessão não vale mais.
    signOut();
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response, path), response.status);
  }
  return (await response.json()) as T;
}

// O backend responde erros de regra como {error: {message}} (409 = "agora não pode").
async function errorMessage(response: Response, path: string): Promise<string> {
  try {
    const payload = await response.json();
    return payload?.error?.message ?? payload?.detail ?? `${response.status} em ${path}`;
  } catch {
    return `${response.status} em ${path}`;
  }
}

export const apiGet = <T>(path: string) => request<T>("GET", path);
export const apiPost = <T>(path: string, body?: unknown) => request<T>("POST", path, body);

// ---------- tipos: espelham as respostas do backend ----------

// Decimais chegam como string para não perder precisão; null = dado ausente, nunca zero.
export type Decimal = string | null;

export type HealthResponse = {
  status: "ok" | "degraded";
  environment: string;
  database: "up" | "down";
  mode: {
    mock_marketplace: boolean;
    mock_ads: boolean;
    dry_run: boolean;
    ai_autonomy_level: number;
    llm_enabled: boolean;
  };
};

export type Zone = "WINNER" | "PROMISING" | "INCONCLUSIVE" | "UNDERPERFORMER" | "NO_DATA";
export type Settlement = "PROVISIONAL" | "PARTIAL" | "SETTLED";

export type PortfolioItem = {
  product_id: number;
  title: string | null;
  state: string;
  tier: "EXPLORATION" | "EXPLOITATION";
  entered_at: string;
  allocated_daily_budget: string;
  zone: Zone;
  roi: Decimal;
  settlement: Settlement;
  clicks: number | null;
};

export type PortfolioResponse = {
  active_count: number;
  total_daily_budget: string;
  items: PortfolioItem[];
};

export type Sizing = {
  data_available: boolean;
  recommended_size: number | null;
  range_min: number;
  range_max: number;
  exploration_slots: number;
  exploitation_slots: number;
  days_to_decision: string | null;
  feasible: boolean;
  assumptions: Record<string, string | number | null>;
  warnings: string[];
};

type TierBudget = { cap: string; used: string; available: string };
export type BudgetStatus = {
  date: string;
  cap: string;
  used: string;
  available: string;
  tiers: { EXPLORATION: TierBudget; EXPLOITATION: TierBudget };
};

export type DailyRow = {
  metric_date: string;
  product_id: number;
  impressions: number | null;
  clicks: number | null;
  ad_spend: Decimal;
  conversions: number | null;
  revenue: Decimal;
  roi: Decimal;
  roas: Decimal;
  cost_data_available: boolean;
  revenue_data_available: boolean;
  settlement: Settlement;
};

export type PerformanceSummary = {
  window_days: number;
  rows: number;
  measured_rows: number;
  ad_spend: Decimal;
  revenue: Decimal;
  profit: Decimal;
  roi: Decimal;
  settled_rows: number;
};

export type Recommendation = {
  id: number;
  decision_type: string;
  subject_type: string;
  subject_id: string | null;
  subject_title: string | null;
  rationale: {
    action?: string;
    what?: string;
    why?: string;
    diagnosis?: string;
    replacement_hint?: string;
    data_used?: Record<string, unknown>;
    expired_reason?: string;
  };
  status: string;
  created_at: string;
};

export type Decision = {
  id: number;
  mode: "RECOMMEND" | "EXECUTE";
  decision_type: string;
  autonomy_level: number;
  dry_run: boolean;
  product_in: number | null;
  product_out: number | null;
  payload: { what?: string; why?: string; actor?: string; human_approved?: boolean };
  created_at: string;
};

export const getHealth = () => apiGet<HealthResponse>("/health");
export const getPortfolio = () => apiGet<PortfolioResponse>("/portfolio");
export const getSizing = () => apiGet<Sizing>("/portfolio/sizing");
export const getBudget = () => apiGet<BudgetStatus>("/budget/status");
export const getSummary = (days: number) =>
  apiGet<PerformanceSummary>(`/performance/summary?days=${days}`);
export const getDaily = (days: number) =>
  apiGet<{ items: DailyRow[] }>(`/performance/daily?days=${days}`);
export const getRecommendations = () =>
  apiGet<{ items: Recommendation[] }>("/recommendations?status=PENDING");
export const getDecisions = () => apiGet<{ items: Decision[] }>("/decisions?limit=30");
export const approveRecommendation = (id: number) =>
  apiPost<{ executed: boolean }>(`/recommendations/${id}/approve`);
export const rejectRecommendation = (id: number, reason?: string) =>
  apiPost<{ status: string }>(`/recommendations/${id}/reject`, { reason });

export type CampaignRow = {
  id: number;
  name: string;
  external_id: string | null;
  status: string;
  review_status: "UNREVIEWED" | "APPROVED" | "REJECTED" | "ARCHIVED";
  daily_budget: Decimal;
  reviewed_by: string | null;
  created_at: string;
};

export const getCampaigns = (reviewStatus?: string) =>
  apiGet<{ items: CampaignRow[] }>(
    `/campaigns${reviewStatus ? `?review_status=${reviewStatus}` : ""}`,
  );
export const reviewCampaign = (id: number, decision: "APPROVED" | "REJECTED") =>
  apiPost<{ review_status: string }>(`/campaigns/${id}/review`, { decision });

// ---------- fila de aprovação de pins ----------

export type PublishStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "PUBLISHED"
  | "BLOCKED"
  | "FAILED";

export type QueueItem = {
  creative_id: number;
  product_id: number;
  title: string | null;
  price: Decimal;
  commission_value: Decimal;
  image_url: string | null;
  headline: string | null;
  caption: string | null;
  created_at: string;
  status: PublishStatus;
  risk_blocked: boolean;
  risk_reason: string | null;
};

export type PublishingQueue = { window_days: number; awaiting: number; items: QueueItem[] };

export const getPublishingQueue = () => apiGet<PublishingQueue>("/publishing/queue");
export const decidePublishing = (creativeIds: number[], decision: "APPROVED" | "REJECTED") =>
  apiPost<{ recorded: number; unchanged: number; already_posted: number }>(
    "/publishing/decisions",
    { creative_ids: creativeIds, decision },
  );

// ---------- produtos ----------

export type ProductSnapshot = {
  captured_at: string;
  price: Decimal;
  commission_rate: Decimal;
  commission_value: Decimal;
  rating: Decimal;
  rating_count: number | null;
  sales_volume: number | null;
  stock: number | null;
  // campo -> a API informou? É daqui que sai o "—" honesto: sem dado não é zero.
  data_available: Record<string, boolean>;
};

export type OpportunityScore = {
  score: Decimal;
  data_available: boolean;
  missing_fields: string[];
  algorithm_version: string;
  computed_at: string;
  components?: Record<
    string,
    { value: string | null; weight: string; available: boolean; note?: string; reason?: string }
  >;
};

/** Receita esperada por clique: comissão em dinheiro x taxa de conversão estimada.
 *  `data_available: false` significa que ainda é prior — nenhum clique próprio por trás. */
export type ExpectedValue = {
  ev_per_click: string;
  commission_value: string;
  cvr_estimate: string;
  cvr_lower: string;
  cvr_upper: string;
  clicks: number;
  conversions: number;
  momentum: string | null;
  prior_source: string;
  data_available: boolean;
  algorithm_version: string;
  computed_at: string;
  components?: Record<string, unknown>;
};

export type ProductRow = {
  id: number;
  title: string;
  product_url: string;
  image_url: string | null;
  marketplace: string;
  category: { id: string; name: string } | null;
  state: string;
  state_since: string;
  last_reason_code: string | null;
  last_actor: string | null;
  snapshot: ProductSnapshot | null;
  opportunity: OpportunityScore | null;
  expected_value: ExpectedValue | null;
};

export type ProductList = {
  total: number;
  counts: Record<string, number>;
  categories: { id: string; name: string; count: number }[];
  items: ProductRow[];
};

export type ProductDetail = {
  id: number;
  title: string;
  product_url: string;
  image_url: string | null;
  marketplace: string | null;
  category_path: string[] | null;
  category: { id: string; name: string } | null;
  first_seen_at: string;
  last_seen_at: string;
  state: string | null;
  state_since: string | null;
  history: {
    from_state: string | null;
    to_state: string;
    reason_code: string;
    reason_detail: string | null;
    actor: string;
    metrics_used: Record<string, unknown> | null;
    created_at: string;
  }[];
  snapshots: ProductSnapshot[];
  scores: OpportunityScore[];
  expected_values: ExpectedValue[];
  links: { sub_id: string; short_url: string | null; channel: string }[];
};

export type ProductQuery = {
  state?: string;
  q?: string;
  category?: string;
  sort: "ev" | "score" | "recent" | "commission" | "sales";
  limit: number;
  offset: number;
};

export const getProducts = (query: ProductQuery) => {
  const params = new URLSearchParams({
    sort: query.sort,
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.state) params.set("state", query.state);
  if (query.q) params.set("q", query.q);
  if (query.category) params.set("category", query.category);
  return apiGet<ProductList>(`/products?${params}`);
};
export const getProduct = (id: number) => apiGet<ProductDetail>(`/products/${id}`);
