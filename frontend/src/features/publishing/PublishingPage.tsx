import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Pill } from "../../components/Badge";
import {
  decidePublishing,
  getPublishingQueue,
  type PublishStatus,
  type QueueItem,
} from "../../lib/api";
import { dateTime, money } from "../../lib/format";

// Pílula = ícone + rótulo: a cor sozinha não pode carregar o significado.
const STATUS: Record<PublishStatus, { label: string; tone: "neutral" | "warn" | "info" }> = {
  PENDING: { label: "◔ Aguardando você", tone: "warn" },
  APPROVED: { label: "✓ Aprovado · sai na próxima hora", tone: "info" },
  REJECTED: { label: "✕ Rejeitado", tone: "neutral" },
  PUBLISHED: { label: "● Publicado", tone: "neutral" },
  BLOCKED: { label: "⊘ Barrado por risco", tone: "warn" },
  FAILED: { label: "! Recusado pelo Pinterest", tone: "warn" },
};

const FILTERS = [
  { key: "PENDING", label: "Aguardando" },
  { key: "APPROVED", label: "Aprovados" },
  { key: "REJECTED", label: "Rejeitados" },
  { key: "DONE", label: "Já processados" },
  { key: "ALL", label: "Todos" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

const matches = (filter: FilterKey, status: PublishStatus) =>
  filter === "ALL"
    ? true
    : filter === "DONE"
      ? status === "PUBLISHED" || status === "BLOCKED" || status === "FAILED"
      : status === filter;

// Só dá para decidir o que ainda não saiu e não foi barrado por risco.
const decidable = (i: QueueItem) =>
  !i.risk_blocked && (i.status === "PENDING" || i.status === "APPROVED" || i.status === "REJECTED");

export default function PublishingPage() {
  const queryClient = useQueryClient();
  const queue = useQuery({ queryKey: ["publishing-queue"], queryFn: getPublishingQueue });
  const [filter, setFilter] = useState<FilterKey>("PENDING");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const decide = useMutation({
    mutationFn: ({ ids, decision }: { ids: number[]; decision: "APPROVED" | "REJECTED" }) =>
      decidePublishing(ids, decision),
    onSuccess: () => {
      setSelected(new Set());
      return queryClient.invalidateQueries({ queryKey: ["publishing-queue"] });
    },
  });

  const items = queue.data?.items ?? [];
  const visible = useMemo(() => items.filter((i) => matches(filter, i.status)), [items, filter]);
  const selectable = visible.filter(decidable);
  const count = (key: FilterKey) => items.filter((i) => matches(key, i.status)).length;

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const chosen = [...selected].filter((id) => selectable.some((i) => i.creative_id === id));

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Publicação</h1>
        <p className="text-sm text-slate-500">
          Pins propostos pelo MP. <strong className="text-slate-300">Só sai o que você aprovar.</strong>
        </p>
      </header>

      <p className="rounded border border-slate-700 bg-slate-900/50 p-3 text-sm text-slate-400">
        O Pinterest exige que cada pin seja escolhido por uma pessoa, então o MP não publica nada
        por conta própria. Aprovar marca o pin para sair na próxima rodada horária; rejeitar o tira
        da fila. Dá para mudar de ideia enquanto ele não saiu. Mostra os últimos{" "}
        {queue.data?.window_days ?? 3} dias. Produto barrado por risco de marca não pode ser
        aprovado: esse filtro vale mesmo para o que você aprovar.
      </p>

      {decide.error && (
        <p role="alert" className="text-sm text-amber-300">
          {decide.error.message}
        </p>
      )}

      <nav className="flex flex-wrap gap-2" aria-label="Filtro da fila">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => {
              setFilter(f.key);
              setSelected(new Set());
            }}
            aria-pressed={filter === f.key}
            className={`rounded border px-3 py-1 text-sm ${
              filter === f.key
                ? "border-sky-700 bg-sky-950/40 text-sky-200"
                : "border-slate-700 text-slate-400 hover:bg-slate-800"
            }`}
          >
            {f.label} <span className="tabular-nums text-slate-500">{count(f.key)}</span>
          </button>
        ))}
      </nav>

      {selectable.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-900/50 p-3 text-sm">
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={chosen.length === selectable.length}
              onChange={(e) =>
                setSelected(e.target.checked ? new Set(selectable.map((i) => i.creative_id)) : new Set())
              }
            />
            Selecionar todos desta lista
          </label>
          <span className="text-slate-500">{chosen.length} selecionado(s)</span>
          <span className="ml-auto flex gap-2">
            <button
              disabled={chosen.length === 0 || decide.isPending}
              onClick={() => decide.mutate({ ids: chosen, decision: "REJECTED" })}
              className="rounded border border-slate-700 px-3 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
            >
              Rejeitar selecionados
            </button>
            <button
              disabled={chosen.length === 0 || decide.isPending}
              onClick={() => decide.mutate({ ids: chosen, decision: "APPROVED" })}
              className="rounded bg-sky-700 px-3 py-1 font-medium text-white hover:bg-sky-600 disabled:opacity-40"
            >
              Aprovar selecionados
            </button>
          </span>
        </div>
      )}

      <section className="space-y-3">
        {queue.isLoading ? (
          <p className="p-6 text-center text-sm text-slate-500">Carregando…</p>
        ) : visible.length === 0 ? (
          <p className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-center text-sm text-slate-500">
            {items.length === 0
              ? "Nada proposto ainda. Os pins aparecem aqui depois do pacote diário das 06:00."
              : "Nada nesta lista."}
          </p>
        ) : (
          visible.map((i) => {
            const status = STATUS[i.status];
            return (
              <article
                key={i.creative_id}
                className="flex gap-4 rounded-lg border border-slate-800 bg-slate-900/50 p-4"
              >
                {decidable(i) && (
                  <input
                    type="checkbox"
                    className="mt-1 shrink-0"
                    aria-label={`Selecionar ${i.title ?? `criativo ${i.creative_id}`}`}
                    checked={selected.has(i.creative_id)}
                    onChange={() => toggle(i.creative_id)}
                  />
                )}
                {i.image_url ? (
                  <img
                    src={i.image_url}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="h-24 w-24 shrink-0 rounded object-cover"
                  />
                ) : (
                  <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded border border-dashed border-slate-700 text-xs text-slate-600">
                    sem imagem
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={status.tone}>{status.label}</Pill>
                    {i.risk_blocked && (
                      <Pill tone="warn">⊘ Risco de marca ({i.risk_reason})</Pill>
                    )}
                    <span className="text-xs text-slate-600">{dateTime(i.created_at)}</span>
                  </div>
                  <h2 className="truncate text-sm font-medium text-slate-100" title={i.title ?? ""}>
                    {i.title ?? `Produto ${i.product_id}`}
                  </h2>
                  <p className="text-xs text-slate-500">
                    Preço {money(i.price)} · comissão {money(i.commission_value)}
                  </p>
                  {i.caption && (
                    <details className="text-sm text-slate-400">
                      <summary className="cursor-pointer text-slate-500">Ver legenda</summary>
                      <p className="mt-1 whitespace-pre-line">{i.caption}</p>
                    </details>
                  )}
                </div>
                {decidable(i) && (
                  <span className="flex shrink-0 flex-col gap-2">
                    <button
                      disabled={decide.isPending || i.status === "APPROVED"}
                      onClick={() => decide.mutate({ ids: [i.creative_id], decision: "APPROVED" })}
                      className="rounded bg-sky-700 px-3 py-1 text-xs font-medium text-white hover:bg-sky-600 disabled:opacity-40"
                    >
                      Aprovar
                    </button>
                    <button
                      disabled={decide.isPending || i.status === "REJECTED"}
                      onClick={() => decide.mutate({ ids: [i.creative_id], decision: "REJECTED" })}
                      className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                    >
                      Rejeitar
                    </button>
                  </span>
                )}
              </article>
            );
          })
        )}
      </section>
    </div>
  );
}
