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
