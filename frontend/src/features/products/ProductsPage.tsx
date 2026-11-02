import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Pill } from "../../components/Badge";
import { getProducts, type ProductQuery, type ProductRow } from "../../lib/api";
import { MISSING, integer, money, num, ratePct, score } from "../../lib/format";
import ProductDrawer from "./ProductDrawer";
import { STATES, reasonLabel, stateLabel } from "./labels";

const PAGE = 25;
const SORTS: { key: ProductQuery["sort"]; label: string }[] = [
  { key: "ev", label: "Maior receita esperada" },
  { key: "score", label: "Maior score" },
  { key: "recent", label: "Mais recentes" },
  { key: "sales", label: "Mais vendidos" },
  { key: "commission", label: "Maior comissão por venda" },
];
const TONE = { neutral: "neutral", info: "info", warn: "warn", good: "info", bad: "warn" } as const;

export default function ProductsPage() {
  const [state, setState] = useState<string | undefined>();
  const [category, setCategory] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<ProductQuery["sort"]>("ev");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  // Digitar não dispara uma consulta por letra.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const query = useQuery({
    queryKey: ["products", state, category, q, sort, offset],
    queryFn: () => getProducts({ state, category, q: q || undefined, sort, limit: PAGE, offset }),
    placeholderData: (previous) => previous,
  });

  const data = query.data;
  const counts = data?.counts ?? {};
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const total = data?.total ?? 0;

  const choose = (key: string | undefined) => {
    setState(key);
    setOffset(0);
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Produtos</h1>
        <p className="text-sm text-slate-500">
          Tudo que o funil já viu, com o que a API informou, a nota do motor e o motivo de cada decisão.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar no título…"
          aria-label="Buscar produto"
          className="w-64 rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-sky-600"
        />
        {(data?.categories.length ?? 0) > 0 && (
          <label className="flex items-center gap-2 text-sm text-slate-400">
            Categoria
            <select
              value={category ?? ""}
              onChange={(e) => {
                setCategory(e.target.value || undefined);
                setOffset(0);
              }}
              className="max-w-[220px] rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-200"
            >
              <option value="">Todas</option>
              {data?.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.count})
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-400">
          Ordenar por
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as ProductQuery["sort"]);
              setOffset(0);
            }}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-200"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div role="group" aria-label="Filtrar por estado" className="flex flex-wrap gap-2">
        <Chip active={!state} onClick={() => choose(undefined)} label="Todos" count={all} />
        {STATES.filter((s) => counts[s.key]).map((s) => (
          <Chip
            key={s.key}
            active={state === s.key}
            onClick={() => choose(s.key)}
            label={s.label}
            count={counts[s.key]}
          />
        ))}
      </div>

      {query.error && (
        <p className="rounded border border-red-800/60 bg-red-950/30 p-3 text-sm text-red-300">
          Não foi possível carregar os produtos.
        </p>
      )}

      <section
        className={`rounded-lg border border-slate-800 bg-slate-900/50 transition ${query.isFetching ? "opacity-70" : ""}`}
      >
        {query.isLoading ? (
          <p className="p-6 text-center text-sm text-slate-500">Carregando…</p>
        ) : !data || data.items.length === 0 ? (
          <Empty hasAny={all > 0} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="px-4 py-3 font-normal">Produto</th>
                  <th className="px-2 py-3 font-normal">Categoria</th>
                  <th className="px-2 py-3 font-normal">Estado</th>
                  <th className="px-2 py-3 text-right font-normal">Preço</th>
                  <th className="px-2 py-3 text-right font-normal">Comissão</th>
                  <th className="px-2 py-3 text-right font-normal">Vendas</th>
                  <th className="px-2 py-3 text-right font-normal">Nota</th>
                  <th
                    className="px-2 py-3 text-right font-normal"
                    title="Comissão por venda x conversão estimada. É por este número que a vaga do portfólio é decidida."
                  >
                    R$/clique
                  </th>
                  <th className="px-4 py-3 text-right font-normal">Score</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <Row key={p.id} p={p} onOpen={() => setOpen(p.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {total > 0 && (
        <nav className="flex items-center justify-between text-sm text-slate-400" aria-label="Paginação">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, total)} de {integer(total)}
          </span>
          <span className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
              className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
            >
              Próxima
            </button>
          </span>
        </nav>
      )}

      {open !== null && <ProductDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Chip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 text-xs transition ${
        active
          ? "border-sky-600 bg-sky-950/60 text-sky-200"
          : "border-slate-700 text-slate-400 hover:bg-slate-800"
      }`}
    >
      {label} <span className="tabular-nums text-slate-500">{integer(count)}</span>
    </button>
  );
}

function Row({ p, onOpen }: { p: ProductRow; onOpen: () => void }) {
  const s = p.snapshot;
  const ev = p.expected_value;
  const tone = TONE[STATES.find((x) => x.key === p.state)?.tone ?? "neutral"];
  // Em DISCOVERY sem preço ou comissão o produto não foi reprovado: está esperando dado.
  const waiting = p.state === "DISCOVERY" && (num(s?.price) === null || num(s?.commission_rate) === null);
  const reason = waiting ? "Aguardando preço e comissão" : reasonLabel(p.last_reason_code);

  return (
    <tr
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      tabIndex={0}
      className="cursor-pointer border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30 focus:bg-slate-800/40 focus:outline-none"
    >
      <td className="max-w-[280px] truncate px-4 py-3 text-slate-200" title={p.title}>
        {p.title}
      </td>
      <td className="max-w-[150px] truncate px-2 py-3 text-xs text-slate-400" title={p.category?.name}>
        {p.category?.name ?? MISSING}
      </td>
      <td className="px-2 py-3">
        <Pill tone={tone}>{stateLabel(p.state)}</Pill>
        {reason && <div className="mt-1 text-xs text-slate-500">{reason}</div>}
      </td>
      <td className="px-2 py-3 text-right tabular-nums">{money(s?.price)}</td>
      <td className="px-2 py-3 text-right tabular-nums">
        {ratePct(s?.commission_rate)}
        <div className="text-xs text-slate-500">{s?.commission_value ? money(s.commission_value) : ""}</div>
      </td>
      <td className="px-2 py-3 text-right tabular-nums">{integer(s?.sales_volume)}</td>
      <td className="px-2 py-3 text-right tabular-nums">
        {s?.rating == null ? MISSING : String(s.rating).replace(".", ",")}
      </td>
      <td className="px-2 py-3 text-right tabular-nums">
        {ev ? (
          <>
            <span className="text-slate-200">{money(ev.ev_per_click)}</span>
            <div
              className={ev.data_available ? "text-[11px] text-slate-500" : "text-[11px] text-amber-400/80"}
              title={
                ev.data_available
                  ? `${integer(ev.clicks)} cliques medidos, ${integer(ev.conversions)} vendas`
                  : "estimativa sem clique próprio: ainda é prior"
              }
            >
              {ev.data_available ? `${integer(ev.clicks)} cliques` : "sem clique"}
            </div>
          </>
        ) : (
          MISSING
        )}
      </td>
      <td className="px-4 py-3 text-right tabular-nums">
        {p.opportunity ? (
          <>
            {score(p.opportunity.score)}
            {!p.opportunity.data_available && (
              <div className="text-[11px] text-amber-400/80" title="faltou dado: não promove">
                indicativo
              </div>
            )}
          </>
        ) : (
          MISSING
        )}
      </td>
    </tr>
  );
}

function Empty({ hasAny }: { hasAny: boolean }) {
  return (
    <p className="p-8 text-center text-sm text-slate-500">
      {hasAny
        ? "Nenhum produto com esse filtro."
        : "Ainda não há produtos. Eles aparecem depois que o workflow de descoberta rodar com DRY_RUN desligado."}
    </p>
  );
}

