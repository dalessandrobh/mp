import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Pill } from "../../components/Badge";
import { getCampaigns, reviewCampaign, type CampaignRow } from "../../lib/api";
import { dateTime, money } from "../../lib/format";

const REVIEW_LABEL: Record<CampaignRow["review_status"], string> = {
  UNREVIEWED: "Aguardando revisão",
  APPROVED: "Aprovada",
  REJECTED: "Rejeitada",
  ARCHIVED: "Arquivada",
};

export default function CampaignsPage() {
  const queryClient = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => getCampaigns() });

  const review = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: "APPROVED" | "REJECTED" }) =>
      reviewCampaign(id, decision),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
  });

  const items = campaigns.data?.items ?? [];
  const waiting = items.filter((c) => c.review_status === "UNREVIEWED").length;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Campanhas</h1>
        <p className="text-sm text-slate-500">
          Campanhas criadas pelo MP. Todas nascem <strong className="text-slate-300">pausadas</strong>.
        </p>
      </header>

      <p className="rounded border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-400">
        Marcar como revisada <strong className="text-slate-300">não ativa nada</strong> no Meta: é só
        o seu visto de que você olhou a campanha. Para ativar (ou desativar), use o Gerenciador de
        Anúncios — a plataforma não tem como fazer isso. Com muitas campanhas sem revisão a criação
        de novas é bloqueada.
      </p>

      {review.error && (
        <p role="alert" className="text-sm text-amber-300">{review.error.message}</p>
      )}

      <section className="rounded-lg border border-slate-800 bg-slate-900/50">
        {campaigns.isLoading ? (
          <p className="p-6 text-center text-sm text-slate-500">Carregando…</p>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-slate-500">
            Nenhuma campanha criada ainda. Elas aparecem aqui depois do workflow de criação (nível de
            autonomia 4).
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="px-4 py-3 font-normal">Campanha</th>
                  <th className="px-2 py-3 font-normal">No Meta</th>
                  <th className="px-2 py-3 text-right font-normal">Orçamento/dia</th>
                  <th className="px-2 py-3 font-normal">Revisão</th>
                  <th className="px-2 py-3 font-normal">Criada</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id} className="border-b border-slate-800/60 last:border-0">
                    <td className="max-w-[260px] truncate px-4 py-3 text-slate-200" title={c.name}>
                      {c.name}
                    </td>
                    <td className="px-2 py-3 text-slate-400">{c.status}</td>
                    <td className="px-2 py-3 text-right tabular-nums">{money(c.daily_budget)}</td>
                    <td className="px-2 py-3">
                      <Pill tone={c.review_status === "UNREVIEWED" ? "warn" : "neutral"}>
                        {REVIEW_LABEL[c.review_status]}
                      </Pill>
                    </td>
                    <td className="px-2 py-3 text-slate-500">{dateTime(c.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      {c.review_status === "UNREVIEWED" && (
                        <span className="flex justify-end gap-2">
                          <button
                            disabled={review.isPending}
                            onClick={() => review.mutate({ id: c.id, decision: "REJECTED" })}
                            className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                          >
                            Rejeitar
                          </button>
                          <button
                            disabled={review.isPending}
                            onClick={() => review.mutate({ id: c.id, decision: "APPROVED" })}
                            className="rounded bg-sky-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-600 disabled:opacity-50"
                          >
                            Marcar revisada
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {waiting > 0 && (
        <p className="text-xs text-slate-600">{waiting} aguardando revisão.</p>
      )}
    </div>
  );
}
