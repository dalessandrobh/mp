import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Pill } from "../../components/Badge";
import {
  approveRecommendation,
  getDecisions,
  getHealth,
  getRecommendations,
  rejectRecommendation,
  type Decision,
  type Recommendation,
} from "../../lib/api";
import { dateTime } from "../../lib/format";

// Só estas ações MUDAM algo quando aprovadas; as outras são informativas (“ciente”).
const EXECUTABLE = new Set(["ENTER_PORTFOLIO", "GRADUATE", "REPLACE_PRODUCT"]);

const TYPE_LABEL: Record<string, string> = {
  PROMOTE: "Promover",
  REPLACE: "Substituir",
  KEEP: "Manter",
  RESIZE_PORTFOLIO: "Redimensionar",
};

const DIAGNOSIS: Record<string, string> = {
  CREATIVE_WEAK: "Criativo/segmentação fraca",
  OFFER_WEAK: "Oferta, preço ou landing fraca",
  COMMISSION_INSUFFICIENT: "Comissão insuficiente para o CPC",
  HEALTHY: "Saudável",
  INSUFFICIENT_DATA: "Dados insuficientes",
};

// Rótulos em português para os campos que o motor registra em data_used.
const DATA_LABEL: Record<string, string> = {
  opportunity_score: "Opportunity Score",
  daily_test_budget: "Orçamento de teste/dia",
  algorithm_version: "Versão do algoritmo",
  active_count: "Produtos ativos",
  clicks: "Cliques",
  impressions: "Impressões",
  ctr: "CTR",
  cvr: "Conversão",
  roi: "ROI",
  settlement: "Maturidade do dado",
  zone: "Zona",
};

export default function IntelligencePage() {
  const queryClient = useQueryClient();
  const recs = useQuery({ queryKey: ["recommendations"], queryFn: getRecommendations });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: getDecisions });
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth });
  const [feedback, setFeedback] = useState<{ id: number; ok: boolean; text: string } | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["recommendations"] });
    queryClient.invalidateQueries({ queryKey: ["decisions"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    queryClient.invalidateQueries({ queryKey: ["budget"] });
  };

  const approve = useMutation({
    mutationFn: (rec: Recommendation) => approveRecommendation(rec.id),
    onSuccess: (data, rec) => {
      setFeedback({ id: rec.id, ok: true, text: data.executed ? "Executada." : "Registrada como ciente." });
      refresh();
    },
    // 409 = a regra barrou (dado envelheceu, sem vaga, orçamento): a mensagem explica o porquê.
    onError: (error, rec) => setFeedback({ id: rec.id, ok: false, text: error.message }),
  });

  const reject = useMutation({
    mutationFn: ({ rec, reason }: { rec: Recommendation; reason?: string }) =>
      rejectRecommendation(rec.id, reason),
    onSuccess: refresh,
  });

  const pending = recs.data?.items ?? [];
  const level = health.data?.mode.ai_autonomy_level;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Inteligência</h1>
        <p className="text-sm text-slate-500">
          O que o motor propõe e o que já foi decidido. Autonomia atual:{" "}
          <span className="text-slate-300">{level ? `nível ${level}` : "…"}</span>
          {level !== undefined && level < 3 && " — mudanças de portfólio só acontecem se você aprovar aqui."}
        </p>
      </header>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Recomendações pendentes ({pending.length})
        </h2>

        {recs.isLoading ? (
          <p className="text-sm text-slate-500">Carregando…</p>
        ) : pending.length === 0 ? (
          <p className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-center text-sm text-slate-500">
            Nada pendente. O motor roda em <code>portfolio/analyze</code>.
          </p>
        ) : (
          <ul className="space-y-3">
            {pending.map((rec) => (
              <RecommendationCard
                key={rec.id}
                rec={rec}
                busy={approve.isPending || reject.isPending}
                feedback={feedback?.id === rec.id ? feedback : null}
                onApprove={() => {
                  const executable = EXECUTABLE.has(rec.rationale.action ?? "");
                  if (
                    !executable ||
                    window.confirm(
                      `Aprovar executa a mudança agora:\n\n${rec.rationale.what ?? "ação"}\n\nContinuar?`,
                    )
                  ) {
                    setFeedback(null);
                    approve.mutate(rec);
                  }
                }}
                onReject={() => {
                  const reason = window.prompt("Motivo da rejeição (opcional):") ?? undefined;
                  reject.mutate({ rec, reason: reason || undefined });
                }}
              />
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-slate-600">
          Aqui nada ativa campanha no Meta: campanhas nascem pausadas e a ativação é sempre manual
          no Gerenciador de Anúncios.
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Decisões recentes
        </h2>
        <DecisionsTable items={decisions.data?.items ?? []} loading={decisions.isLoading} />
      </section>
    </div>
  );
}

function RecommendationCard({
  rec,
  busy,
  feedback,
  onApprove,
  onReject,
}: {
  rec: Recommendation;
  busy: boolean;
  feedback: { ok: boolean; text: string } | null;
  onApprove: () => void;
  onReject: () => void;
}) {
  const r = rec.rationale;
  const executable = EXECUTABLE.has(r.action ?? "");
  const data = Object.entries(r.data_used ?? {}).filter(([, v]) => v !== null && typeof v !== "object");

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={rec.decision_type === "REPLACE" ? "warn" : "info"}>
              {TYPE_LABEL[rec.decision_type] ?? rec.decision_type}
            </Pill>
            {rec.subject_title && <span className="text-sm text-slate-200">{rec.subject_title}</span>}
          </div>
          <p className="text-sm text-slate-100">{r.what ?? "—"}</p>
          {r.why && <p className="text-sm text-slate-400">{r.why}</p>}
          {r.diagnosis && (
            <p className="text-xs text-slate-400">
              Diagnóstico: <span className="text-slate-200">{DIAGNOSIS[r.diagnosis] ?? r.diagnosis}</span>
              {r.replacement_hint && ` — ${r.replacement_hint}`}
            </p>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          <button
            disabled={busy}
            onClick={onReject}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            Rejeitar
          </button>
          <button
            disabled={busy}
            onClick={onApprove}
            className="rounded bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-600 disabled:opacity-50"
          >
            {executable ? "Aprovar e executar" : "Ciente"}
          </button>
        </div>
      </div>

      {data.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 border-t border-slate-800 pt-3 text-xs sm:grid-cols-4">
          {data.map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{DATA_LABEL[k] ?? k.replace(/_/g, " ")}</dt>
              <dd className="text-slate-300">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}

      {feedback && (
        <p role="status" className={`mt-3 text-sm ${feedback.ok ? "text-emerald-300" : "text-amber-300"}`}>
          {feedback.text}
        </p>
      )}
      <p className="mt-2 text-xs text-slate-600">Proposta em {dateTime(rec.created_at)}</p>
    </li>
  );
}

function DecisionsTable({ items, loading }: { items: Decision[]; loading: boolean }) {
  if (loading) return <p className="text-sm text-slate-500">Carregando…</p>;
  if (items.length === 0) {
    return (
      <p className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-center text-sm text-slate-500">
        Nenhuma decisão registrada ainda.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/50">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="px-4 py-3 font-normal">Quando</th>
            <th className="px-2 py-3 font-normal">Decisão</th>
            <th className="px-2 py-3 font-normal">O quê</th>
            <th className="px-2 py-3 font-normal">Quem</th>
            <th className="px-4 py-3 font-normal">Modo</th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.id} className="border-b border-slate-800/60 last:border-0">
              <td className="whitespace-nowrap px-4 py-3 text-slate-500">{dateTime(d.created_at)}</td>
              <td className="px-2 py-3 text-slate-300">{TYPE_LABEL[d.decision_type] ?? d.decision_type}</td>
              <td className="px-2 py-3 text-slate-200">{d.payload.what ?? "—"}</td>
              <td className="px-2 py-3 text-slate-400">
                {d.payload.human_approved ? "Humano" : "Motor"} · nível {d.autonomy_level}
              </td>
              <td className="px-4 py-3">
                {d.dry_run ? <Pill tone="warn">Simulada</Pill> : <Pill>{d.mode === "EXECUTE" ? "Executada" : d.mode}</Pill>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
