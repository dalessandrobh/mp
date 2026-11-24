import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getPins, markPinPosted, type PinCard } from "../../lib/api";

// Campo com o texto já selecionável de uma vez (um toque seleciona tudo) e botão de copiar.
function CopyField({ label, value, multiline = false }: { label: string; value: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false); // sem permissão: o texto continua selecionável com um toque
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>
        <button
          type="button"
          onClick={copy}
          className="rounded border border-slate-600 px-2 py-0.5 text-xs text-slate-200"
        >
          {copied ? "✓ Copiado" : "Copiar"}
        </button>
      </div>
      <div
        className={`select-all rounded bg-slate-900 p-2 text-sm text-slate-100 ${
          multiline ? "whitespace-pre-wrap break-words" : "break-all"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function PinItem({ pin, onPosted }: { pin: PinCard; onPosted: () => void }) {
  const mark = useMutation({ mutationFn: () => markPinPosted(pin.creative_id), onSuccess: onPosted });

  return (
    <li className={`space-y-4 rounded border border-slate-700 p-4 ${pin.posted ? "opacity-60" : ""}`}>
      <div className="flex gap-4">
        <img
          src={pin.image_url}
          alt=""
          loading="lazy"
          className="h-36 w-24 shrink-0 rounded bg-slate-800 object-cover"
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="text-xs text-slate-400">
            {pin.posted ? "✓ Postado" : "◔ Falta postar"}
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
            <a
              href={pin.image_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-slate-600 px-3 py-1.5 text-sm text-slate-200"
            >
              Abrir imagem
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
      </div>

      <div className="space-y-3">
        <CopyField label="Título do pin" value={pin.title} />
        <CopyField label="Descrição" value={pin.description} multiline />
        <CopyField label="Link de destino (pin orgânico)" value={pin.link} />
        <CopyField label="Quadro sugerido" value={pin.board ?? "escolha você"} />
        <CopyField label="URL da imagem" value={pin.image_url} />
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
