import { useQuery } from "@tanstack/react-query";

import StatusCard from "../../components/StatusCard";
import { getHealth } from "../../lib/api";

export default function OverviewPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return <p className="text-sm text-slate-500">Consultando o backend…</p>;
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-red-800/60 bg-red-950/30 p-4">
        <h2 className="font-semibold text-red-300">Backend inacessível</h2>
        <p className="mt-1 text-sm text-red-300/80">
          <code>GET /api/v1/health</code> não respondeu. Verifique se o container{" "}
          <code>mp-backend</code> está no ar e se o Traefik roteia <code>/api</code>.
        </p>
      </div>
    );
  }

  // Um trilho desligado significa que a plataforma pode tocar sistema externo e
  // gastar dinheiro de verdade — por isso aparece como alerta, não como "ok".
  const railsOff = [
    !data.mode.mock_marketplace && "marketplace real",
    !data.mode.mock_ads && "Meta Ads real",
    !data.mode.dry_run && "execução real",
  ].filter(Boolean) as string[];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Visão geral</h1>
        <p className="text-sm text-slate-500">
          Ambiente <span className="text-slate-300">{data.environment}</span>
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard
          label="Status"
          value={data.status === "ok" ? "Operacional" : "Degradado"}
          tone={data.status === "ok" ? "ok" : "danger"}
        />
        <StatusCard
          label="Banco"
          value={data.database === "up" ? "Conectado" : "Indisponível"}
          tone={data.database === "up" ? "ok" : "danger"}
        />
        <StatusCard
          label="Autonomia da IA"
          value={`Nível ${data.mode.ai_autonomy_level}`}
          hint="Campanhas nascem PAUSED em todos os níveis"
          tone="neutral"
        />
        <StatusCard
          label="LLM"
          value={data.mode.llm_enabled ? "Habilitada" : "Desligada"}
          tone="neutral"
        />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Trilhos de segurança
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatusCard
            label="Marketplace"
            value={data.mode.mock_marketplace ? "Mock" : "Real"}
            hint={data.mode.mock_marketplace ? "Nenhuma API externa é chamada" : "Chamando a Shopee"}
            tone={data.mode.mock_marketplace ? "ok" : "warn"}
          />
          <StatusCard
            label="Ads"
            value={data.mode.mock_ads ? "Mock" : "Real"}
            hint={data.mode.mock_ads ? "Nada é criado no Meta" : "Criando estrutura no Meta"}
            tone={data.mode.mock_ads ? "ok" : "warn"}
          />
          <StatusCard
            label="Dry run"
            value={data.mode.dry_run ? "Ligado" : "Desligado"}
            hint={data.mode.dry_run ? "Decisões registradas, não executadas" : "Decisões são executadas"}
            tone={data.mode.dry_run ? "ok" : "warn"}
          />
        </div>

        {railsOff.length > 0 && (
          <p className="mt-3 rounded border border-amber-800/60 bg-amber-950/30 p-3 text-sm text-amber-300">
            Atenção: {railsOff.join(", ")}. A plataforma está tocando sistemas externos.
          </p>
        )}
      </section>
    </div>
  );
}
