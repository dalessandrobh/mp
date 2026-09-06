// Cliente HTTP do dashboard.
//
// A base é relativa de propósito: em produção o Traefik serve o front em / e o
// backend em /api no MESMO host, então não há origem cruzada nem CORS. No dev
// o Vite faz o mesmo desvio (ver vite.config.ts).
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

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new ApiError(`${response.status} em ${path}`, response.status);
  }
  return (await response.json()) as T;
}

// Espelha o retorno de GET /api/v1/health (backend/app/api/v1/routes/health.py).
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

export const getHealth = () => apiGet<HealthResponse>("/health");
