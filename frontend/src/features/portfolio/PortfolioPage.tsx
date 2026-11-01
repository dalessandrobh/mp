import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { SettlementLabel, ZoneBadge } from "../../components/Badge";
import Meter from "../../components/Meter";
import Stat from "../../components/Stat";
import { getBudget, getPortfolio, getSizing } from "../../lib/api";
import { MISSING, dateTime, money, roiPct } from "../../lib/format";

const TIER = { EXPLORATION: "Exploração", EXPLOITATION: "Exploitation" } as const;

export default function PortfolioPage() {
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio });
  const sizing = useQuery({ queryKey: ["sizing"], queryFn: getSizing });
  const budget = useQuery({ queryKey: ["budget"], queryFn: getBudget });

  const items = portfolio.data?.items ?? [];
  const s = sizing.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Portfólio</h1>
        <p className="text-sm text-slate-500">Produtos em teste e ativos, com a leitura do motor.</p>
      </header>

      {(portfolio.error || sizing.error || budget.error) && (
        <p className="rounded border border-red-800/60 bg-red-950/30 p-3 text-sm text-red-300">
          Parte dos dados não carregou. Confira a conexão com o backend.
        </p>
      )}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Produtos ativos"
          value={String(portfolio.data?.active_count ?? MISSING)}
          hint={s ? `Faixa recomendada: ${s.range_min}–${s.range_max}` : undefined}
        />
        <Stat label="Orçamento alocado / dia" value={money(portfolio.data?.total_daily_budget)} />
        <Stat
          label="Tamanho recomendado"
          value={s?.recommended_size != null ? String(s.recommended_size) : "Em aberto"}
          hint={
            s && !s.data_available
              ? "Falta CPC observado: o motor devolve só a faixa"
              : s?.days_to_decision
                ? `~${s.days_to_decision} dias até poder decidir`
                : undefined
          }
        />
        <Stat
          label="Vagas de exploração"
          value={s ? String(s.exploration_slots) : MISSING}
          hint={s ? `+ ${s.exploitation_slots} de exploitation` : undefined}
        />
      </section>

      {s && s.warnings.length > 0 && (
        <ul className="space-y-1 rounded border border-amber-800/60 bg-amber-950/30 p-3 text-sm text-amber-300">
          {s.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {budget.data && (
        <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Orçamento de hoje</h2>
            <span className="text-xs text-slate-500">
              {money(budget.data.used)} de {money(budget.data.cap)} · comprometido + realizado
            </span>
          </div>
          <Meter used={budget.data.used} cap={budget.data.cap} label="Orçamento global do dia" />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {(["EXPLORATION", "EXPLOITATION"] as const).map((tier) => (
              <div key={tier}>
                <div className="mb-1 flex justify-between text-xs text-slate-400">
                  <span>{TIER[tier]}</span>
                  <span>
                    {money(budget.data.tiers[tier].used)} / {money(budget.data.tiers[tier].cap)}
                  </span>
                </div>
                <Meter
                  used={budget.data.tiers[tier].used}
                  cap={budget.data.tiers[tier].cap}
                  label={`Fatia de ${TIER[tier]}`}
                />
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-lg border border-slate-800 bg-slate-900/50">
        {portfolio.isLoading ? (
          <p className="p-6 text-center text-sm text-slate-500">Carregando…</p>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-slate-500">
            Nenhum produto no portfólio ainda. As entradas aparecem em{" "}
            <Link to="/intelligence" className="text-sky-400 underline">Inteligência</Link>, como
            recomendações a aprovar.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="px-4 py-3 font-normal">Produto</th>
                  <th className="px-2 py-3 font-normal">Estado</th>
                  <th className="px-2 py-3 font-normal">Tier</th>
                  <th className="px-2 py-3 font-normal">Leitura do motor</th>
                  <th className="px-2 py-3 text-right font-normal">ROI</th>
                  <th className="px-2 py-3 font-normal">Dado</th>
                  <th className="px-2 py-3 text-right font-normal">Orçamento/dia</th>
                  <th className="px-4 py-3 font-normal">Desde</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.product_id} className="border-b border-slate-800/60 last:border-0">
                    <td className="max-w-[260px] truncate px-4 py-3 text-slate-200" title={item.title ?? ""}>
                      {item.title ?? `Produto ${item.product_id}`}
                    </td>
                    <td className="px-2 py-3 text-slate-400">{item.state}</td>
                    <td className="px-2 py-3 text-slate-400">{TIER[item.tier]}</td>
                    <td className="px-2 py-3"><ZoneBadge zone={item.zone} /></td>
                    <td className="px-2 py-3 text-right tabular-nums">{roiPct(item.roi)}</td>
                    <td className="px-2 py-3"><SettlementLabel settlement={item.settlement} /></td>
                    <td className="px-2 py-3 text-right tabular-nums">{money(item.allocated_daily_budget)}</td>
                    <td className="px-4 py-3 text-slate-500">{dateTime(item.entered_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-xs text-slate-600">
        A zona é calculada agora, com o dado de agora. “Sem dado” e “Inconclusivo” nunca viram
        substituição: o motor espera.
      </p>
    </div>
  );
}
