import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import ColumnChart from "../../components/ColumnChart";
import LineChart from "../../components/LineChart";
import Stat from "../../components/Stat";
import { SettlementLabel } from "../../components/Badge";
import { getDaily, getSummary, type DailyRow, type Settlement } from "../../lib/api";
import { MISSING, integer, money, num, roiPct, shortDate } from "../../lib/format";

const RANGES = [7, 30, 90] as const;
const SETTLEMENT_RANK: Record<Settlement, number> = { PROVISIONAL: 0, PARTIAL: 1, SETTLED: 2 };

type Day = {
  date: string;
  spend: number | null;
  revenue: number | null;
  roi: number | null;
  settlement: Settlement;
};

// Soma por dia. Cada métrica soma só as linhas em que ELA foi medida; sem nenhuma linha
// medida o dia fica null (buraco no gráfico), nunca 0. O ROI só entra com custo E receita
// medidos na mesma linha, senão compararia receita de um produto com custo de outro.
function aggregate(rows: DailyRow[]): Day[] {
  const byDate = new Map<string, DailyRow[]>();
  rows.forEach((r) => byDate.set(r.metric_date, [...(byDate.get(r.metric_date) ?? []), r]));

  return [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, list]) => {
      const sum = (pick: (r: DailyRow) => number | null, ok: (r: DailyRow) => boolean) => {
        const used = list.filter(ok).map(pick).filter((v): v is number => v !== null);
        return used.length ? used.reduce((a, b) => a + b, 0) : null;
      };
      const measured = list.filter((r) => r.cost_data_available && r.revenue_data_available);
      const spendM = measured.reduce((a, r) => a + (num(r.ad_spend) ?? 0), 0);
      const revM = measured.reduce((a, r) => a + (num(r.revenue) ?? 0), 0);

      return {
        date,
        spend: sum((r) => num(r.ad_spend), (r) => r.cost_data_available),
        revenue: sum((r) => num(r.revenue), (r) => r.revenue_data_available),
        roi: measured.length && spendM > 0 ? (revM - spendM) / spendM : null,
        settlement: list.reduce<Settlement>(
          (acc, r) => (SETTLEMENT_RANK[r.settlement] < SETTLEMENT_RANK[acc] ? r.settlement : acc),
          "SETTLED",
        ),
      };
    });
}

export default function FinancialPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [asTable, setAsTable] = useState(false);

  const summary = useQuery({ queryKey: ["summary", days], queryFn: () => getSummary(days) });
  const daily = useQuery({
    queryKey: ["daily", days],
    queryFn: () => getDaily(days),
    placeholderData: (previous) => previous, // refetch mantém o quadro, sem pular o layout
  });

  const series = useMemo(() => aggregate(daily.data?.items ?? []), [daily.data]);
  const dates = series.map((d) => d.date);

  const profitNegative = (num(summary.data?.profit) ?? 0) < 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Financeiro</h1>
          <p className="text-sm text-slate-500">Gasto em anúncios × comissão, por dia.</p>
        </div>
        <div role="group" aria-label="Período" className="flex overflow-hidden rounded border border-slate-700">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={`px-3 py-1.5 text-sm transition ${
                days === r ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800"
              }`}
            >
              {r} dias
            </button>
          ))}
        </div>
      </header>

      {summary.error && <ErrorBox what="o resumo financeiro" />}

      <section className="grid gap-3 lg:grid-cols-4">
        <div className="lg:col-span-2 lg:row-span-2 [&>div]:h-full">
          <Stat
            hero
            label={`ROI — últimos ${days} dias`}
            value={roiPct(summary.data?.roi)}
            hint={
              summary.data?.roi == null
                ? "Sem dias com custo e receita medidos ao mesmo tempo"
                : `${summary.data.measured_rows} de ${summary.data.rows} linhas com custo e receita medidos`
            }
          />
        </div>
        <Stat label="Gasto em anúncios" value={money(summary.data?.ad_spend)} />
        <Stat
          label="Lucro"
          value={money(summary.data?.profit)}
          hint={profitNegative ? "Prejuízo no período" : "Comissão − gasto"}
        />
        <Stat label="Comissão" value={money(summary.data?.revenue)} />
        <Stat
          label="Linhas liquidadas"
          value={`${integer(summary.data?.settled_rows)} / ${integer(summary.data?.rows)}`}
          hint="Só dado liquidado autoriza cortar produto"
        />
      </section>

      <section className="rounded-lg border border-slate-800 bg-[var(--chart-surface)] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Comissão e gasto por dia</h2>
            <p className="text-xs text-slate-500">
              Dia sem dado fica em branco — não é R$ 0. Faixa clara = ainda estimado (não liquidado).
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <Key color="var(--series-1)" label="Comissão" />
            <Key color="var(--series-2)" label="Gasto" />
            <button
              onClick={() => setAsTable((v) => !v)}
              className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
            >
              {asTable ? "Ver gráfico" : "Ver como tabela"}
            </button>
          </div>
        </div>

        <div className={daily.isFetching ? "opacity-60 transition" : "transition"}>
          {daily.isLoading ? (
            <p className="py-10 text-center text-sm text-slate-500">Carregando…</p>
          ) : series.length === 0 ? (
            <Empty />
          ) : asTable ? (
            <DayTable days={series} />
          ) : (
            <>
              <LineChart
                title="Comissão e gasto por dia"
                dates={dates}
                shaded={series.map((d) => d.settlement !== "SETTLED")}
                formatValue={money}
                formatAxis={(v) => (v === 0 ? "0" : `R$ ${new Intl.NumberFormat("pt-BR", { notation: "compact" }).format(v)}`)}
                formatDate={shortDate}
                series={[
                  { key: "revenue", label: "Comissão", color: "var(--series-1)", values: series.map((d) => d.revenue) },
                  { key: "spend", label: "Gasto", color: "var(--series-2)", values: series.map((d) => d.spend) },
                ]}
              />
            </>
          )}
        </div>
      </section>

      {series.length > 0 && !asTable && (
        <section className="rounded-lg border border-slate-800 bg-[var(--chart-surface)] p-4">
          <h2 className="text-sm font-semibold text-slate-200">ROI por dia</h2>
          <p className="mb-3 text-xs text-slate-500">
            Acima de zero a comissão cobriu o gasto. Considera só produtos com custo e receita
            medidos naquele dia.
          </p>
          <ColumnChart
            title="ROI por dia"
            dates={dates}
            values={series.map((d) => d.roi)}
            formatValue={roiPct}
            formatDate={shortDate}
          />
        </section>
      )}
    </div>
  );
}

function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-0.5 w-4" style={{ background: color }} />
      {label}
    </span>
  );
}

function DayTable({ days }: { days: Day[] }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-900 text-xs text-slate-500">
          <tr>
            <th className="py-2 font-normal">Dia</th>
            <th className="py-2 text-right font-normal">Comissão</th>
            <th className="py-2 text-right font-normal">Gasto</th>
            <th className="py-2 text-right font-normal">ROI</th>
            <th className="py-2 pl-4 font-normal">Dado</th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) => (
            <tr key={d.date} className="border-t border-slate-800/70">
              <td className="py-1.5 text-slate-300">{shortDate(d.date)}</td>
              <td className="py-1.5 text-right tabular-nums">{d.revenue === null ? MISSING : money(d.revenue)}</td>
              <td className="py-1.5 text-right tabular-nums">{d.spend === null ? MISSING : money(d.spend)}</td>
              <td className="py-1.5 text-right tabular-nums">{roiPct(d.roi)}</td>
              <td className="py-1.5 pl-4"><SettlementLabel settlement={d.settlement} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty() {
  return (
    <p className="py-10 text-center text-sm text-slate-500">
      Ainda não há performance consolidada neste período. Ela aparece depois do primeiro{" "}
      <code>performance/sync</code> + <code>performance/consolidate</code>.
    </p>
  );
}

function ErrorBox({ what }: { what: string }) {
  return (
    <p className="rounded border border-red-800/60 bg-red-950/30 p-3 text-sm text-red-300">
      Não foi possível carregar {what}.
    </p>
  );
}
