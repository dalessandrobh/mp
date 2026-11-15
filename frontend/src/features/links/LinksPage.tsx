import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { createManualLink, downloadShowcaseCsv } from "../../lib/api";

const CHANNELS = [
  { key: "wa", label: "WhatsApp (canal ou grupo)" },
  { key: "ig", label: "Instagram" },
  { key: "pin", label: "Pinterest (pin manual)" },
];

export default function LinksPage() {
  const [ref, setRef] = useState("");
  const [channel, setChannel] = useState("wa");
  const [copied, setCopied] = useState(false);

  const create = useMutation({
    mutationFn: () => createManualLink(ref.trim(), channel),
    onSuccess: () => setCopied(false),
  });

  const showcase = useMutation({ mutationFn: () => downloadShowcaseCsv(50) });

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-slate-100">Link rastreado</h1>
        <p className="mt-1 text-sm text-slate-400">
          Use este link, e não o do app da Shopee, em qualquer divulgação feita à mão. Só assim a
          venda volta com a origem. Link gerado direto na Shopee chega sem sub_id e o MP não
          consegue atribuir.
        </p>
      </header>

      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (ref.trim()) create.mutate();
        }}
      >
        <label className="block text-sm text-slate-300">
          URL do produto na Shopee (ou o número do item)
          <input
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            placeholder="https://shopee.com.br/product/123456/789012345"
          />
        </label>

        <label className="block text-sm text-slate-300">
          Onde vai divulgar
          <select
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          >
            {CHANNELS.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={create.isPending || !ref.trim()}
          className="rounded bg-slate-200 px-4 py-2 text-sm font-medium text-slate-900 disabled:opacity-50"
        >
          {create.isPending ? "Gerando…" : "Gerar link"}
        </button>
      </form>

      {create.isError && (
        <p role="alert" className="rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">
          {(create.error as Error).message}
        </p>
      )}

      {create.data && (
        <section className="space-y-2 rounded border border-slate-700 p-4">
          <div className="text-sm text-slate-300">{create.data.title ?? `Produto ${create.data.product_id}`}</div>
          <code className="block break-all rounded bg-slate-900 p-3 text-sm text-slate-100">
            {create.data.tracked_url}
          </code>
          <button
            type="button"
            onClick={() => copy(create.data.tracked_url)}
            className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200"
          >
            {copied ? "✓ Copiado" : "Copiar link"}
          </button>
        </section>
      )}

      <section className="space-y-2 border-t border-slate-800 pt-6">
        <h2 className="text-base font-semibold text-slate-100">Lista para a vitrine da Shopee</h2>
        <p className="text-sm text-slate-400">
          Os 50 melhores produtos pelo mesmo critério do pacote diário (sem marca, preço até o
          teto, categorias de pin primeiro). Colunas: posição, título, preço, comissão e URL do
          produto. Links colados direto na vitrine da Shopee não passam pelo MP.
        </p>
        <button
          type="button"
          onClick={() => showcase.mutate()}
          disabled={showcase.isPending}
          className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 disabled:opacity-50"
        >
          {showcase.isPending ? "Gerando…" : "Baixar CSV"}
        </button>
        {showcase.isError && (
          <p role="alert" className="text-sm text-amber-200">
            {(showcase.error as Error).message}
          </p>
        )}
      </section>
    </div>
  );
}
