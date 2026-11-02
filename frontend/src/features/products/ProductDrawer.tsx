import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { getProduct, type OpportunityScore, type ProductSnapshot } from "../../lib/api";
import { MISSING, dateTime, integer, money, ratePct, score } from "../../lib/format";
import { COMPONENTS, FIELDS, reasonLabel, stateLabel } from "./labels";

export default function ProductDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["product", id],
    queryFn: () => getProduct(id),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const latest = data?.snapshots[0] ?? null;
  const latestScore = data?.scores[0] ?? null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        role="dialog"
        aria-label="Detalhe do produto"
        className="h-full w-full max-w-xl overflow-y-auto border-l border-slate-800 bg-slate-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-100">
            {data?.title ?? (isLoading ? "Carregando…" : "Produto")}
          </h2>
          <button
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:bg-slate-800"
          >
            Fechar
          </button>
        </div>

        {error && <p className="text-sm text-red-300">Não foi possível carregar o produto.</p>}

        {data && (
          <div className="space-y-6 text-sm">
            <p className="text-slate-400">
              {stateLabel(data.state ?? "")} desde {data.state_since ? dateTime(data.state_since) : MISSING}
              {" · "}
              <a
                href={data.product_url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-sky-400 underline"
              >
                abrir no marketplace
              </a>
            </p>

            <Section title="O que a API informou (último snapshot)">
              {latest ? <SnapshotGrid s={latest} /> : <Empty>Sem snapshot.</Empty>}
            </Section>

            <Section title="Opportunity Score">
              {latestScore ? <ScoreBlock s={latestScore} /> : <Empty>Ainda não pontuado.</Empty>}
            </Section>

            <Section title="Como chegou aqui">
              <ol className="space-y-2 border-l border-slate-800 pl-4">
                {data.history.map((h, i) => (
                  <li key={i} className="relative">
                    <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-slate-600" />
                    <div className="text-slate-200">
                      {h.from_state ? `${stateLabel(h.from_state)} → ` : ""}
                      <strong>{stateLabel(h.to_state)}</strong>
                      <span className="text-slate-500"> · {dateTime(h.created_at)}</span>
                    </div>
                    <div className="text-xs text-slate-400">
                      {reasonLabel(h.reason_code)} · por {h.actor}
                    </div>
                  </li>
                ))}
              </ol>
            </Section>

            {data.links.length > 0 && (
              <Section title="Links de afiliado">
                <ul className="space-y-1">
                  {data.links.map((l) => (
                    <li key={l.sub_id} className="break-all text-slate-300">
                      {l.short_url ?? MISSING}{" "}
                      <span className="text-xs text-slate-500">({l.sub_id})</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {data.snapshots.length > 1 && (
              <Section title={`Histórico de preço e comissão (${data.snapshots.length} leituras)`}>
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1 font-normal">Lida em</th>
                      <th className="py-1 text-right font-normal">Preço</th>
                      <th className="py-1 text-right font-normal">Comissão</th>
                      <th className="py-1 text-right font-normal">Vendas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.snapshots.map((s) => (
                      <tr key={s.captured_at} className="border-t border-slate-800/70">
                        <td className="py-1 text-slate-400">{dateTime(s.captured_at)}</td>
                        <td className="py-1 text-right tabular-nums">{money(s.price)}</td>
                        <td className="py-1 text-right tabular-nums">{ratePct(s.commission_rate)}</td>
                        <td className="py-1 text-right tabular-nums">{integer(s.sales_volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

const Empty = ({ children }: { children: React.ReactNode }) => (
  <p className="text-slate-500">{children}</p>
);

function SnapshotGrid({ s }: { s: ProductSnapshot }) {
  const cell = (label: string, value: string, field: string) => (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-200">{value}</dd>
      {s.data_available[field] === false && (
        <dd className="text-[11px] text-slate-600">a API não informa</dd>
      )}
    </div>
  );
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {cell("Preço", money(s.price), "price")}
      {cell("Comissão", ratePct(s.commission_rate), "commission_rate")}
      {cell("Comissão por venda", money(s.commission_value), "commission_rate")}
      {cell("Vendas", integer(s.sales_volume), "sales_volume")}
      {cell("Nota", s.rating === null ? MISSING : String(s.rating).replace(".", ","), "rating")}
      {cell("Avaliações", integer(s.rating_count), "rating_count")}
      {cell("Estoque", integer(s.stock), "stock")}
    </dl>
  );
}

function ScoreBlock({ s }: { s: OpportunityScore }) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold text-slate-100">{score(s.score)}</span>
        <span className="text-slate-500">de 100</span>
        {!s.data_available && (
          <span
            title="Faltou dado que o marketplace costuma informar: este score é indicativo e não promove o produto."
            className="rounded-full border border-amber-700/60 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300"
          >
            indicativo
          </span>
        )}
      </div>
      {!s.data_available && s.missing_fields.length > 0 && (
        <p className="text-xs text-amber-300/80">
          Faltando: {s.missing_fields.map((f) => FIELDS[f] ?? f).join(", ")}.
        </p>
      )}
      <table className="w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="py-1 font-normal">Componente</th>
            <th className="py-1 text-right font-normal">Nota</th>
            <th className="py-1 text-right font-normal">Peso</th>
            <th className="py-1 pl-3 font-normal">Observação</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(s.components ?? {}).map(([key, c]) => (
            <tr key={key} className="border-t border-slate-800/70">
              <td className="py-1 text-slate-300">{COMPONENTS[key] ?? key}</td>
              <td className="py-1 text-right tabular-nums">{c.value === null ? MISSING : score(c.value)}</td>
              <td className="py-1 text-right tabular-nums">{(Number(c.weight) * 100).toFixed(0)}%</td>
              <td className="py-1 pl-3 text-slate-500">
                {c.reason === "unsupported"
                  ? "o marketplace não informa; fora da conta"
                  : c.note === "sales_proxy"
                    ? "confiança estimada pelas vendas"
                    : !c.available
                      ? "sem dado"
                      : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-slate-600">
        Algoritmo {s.algorithm_version}, calculado em {dateTime(s.computed_at)}.
      </p>
    </div>
  );
}
