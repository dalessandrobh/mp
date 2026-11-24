import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getPins, markPinPosted, type PinCard } from "../../lib/api";

function PinItem({ pin, onPosted }: { pin: PinCard; onPosted: () => void }) {
  const mark = useMutation({ mutationFn: () => markPinPosted(pin.creative_id), onSuccess: onPosted });

  return (
    <li className={`flex gap-4 rounded border border-slate-700 p-4 ${pin.posted ? "opacity-60" : ""}`}>
      <img
        src={pin.image_url}
        alt=""
        loading="lazy"
        className="h-36 w-24 shrink-0 rounded bg-slate-800 object-cover"
      />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-sm font-medium text-slate-100">{pin.title}</div>
        <div className="text-xs text-slate-400">
          Quadro: {pin.board ?? "escolha você"} · {pin.posted ? "✓ postado" : "◔ falta postar"}
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={pin.pin_it_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-900"
          >
            Abrir no Pinterest
          </a>
          {!pin.posted && (
            <button
              type="button"
              onClick={() => mark.mutate()}
              disabled={mark.isPending}
              className="rounded border border-slate-600 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            >
              {mark.isPending ? "Salvando…" : "Marcar como postado"}
            </button>
          )}
        </div>
        {mark.isError && (
          <p role="alert" className="text-xs text-amber-200">
            {(mark.error as Error).message}
          </p>
        )}
      </div>
    </li>
  );
}

export default function PinsPage() {
  const queryClient = useQueryClient();
  const pins = useQuery({ queryKey: ["pins"], queryFn: getPins });

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-slate-100">Pins do dia</h1>
        <p className="mt-1 text-sm text-slate-400">
          Toque em <strong>Abrir no Pinterest</strong>: a janela já vem com imagem, link e
          descrição. Escolha o quadro e salve. Depois marque como postado aqui. Postar de 1 a 3
          por dia rende mais que o pacote inteiro de uma vez.
        </p>
      </header>

      {pins.isLoading && <p className="text-sm text-slate-400">Carregando…</p>}
      {pins.isError && (
        <p role="alert" className="rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">
          {(pins.error as Error).message}
        </p>
      )}

      {pins.data && (
        <>
          <p className="text-sm text-slate-300">
            {pins.data.pending} {pins.data.pending === 1 ? "pin falta" : "pins faltam"} postar
            (últimos 3 dias).
          </p>
          {pins.data.items.length === 0 && (
            <p className="text-sm text-slate-400">
              Nenhum pin gerado ainda. O pacote sai às 06:00.
            </p>
          )}
          <ul className="space-y-3">
            {pins.data.items.map((pin) => (
              <PinItem
                key={pin.creative_id}
                pin={pin}
                onPosted={() => queryClient.invalidateQueries({ queryKey: ["pins"] })}
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
