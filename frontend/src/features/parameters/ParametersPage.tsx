import { useQuery } from "@tanstack/react-query";

import { getParameters, type ParameterItem } from "../../lib/api";

// Só leitura: mostra o que o backend usa agora. Mudar um valor continua sendo um deploy (ambiente)
// ou um ajuste no banco, de propósito — o painel não altera autonomia nem orçamento.
const SOURCE: Record<ParameterItem["source"], { label: string; cls: string; hint: string }> = {
  banco: {
    label: "banco",
    cls: "border-sky-700/60 bg-sky-950/40 text-sky-300",
    hint: "Valor gravado em config_parameters; vence o ambiente",
  },
  ambiente: {
    label: "ambiente",
    cls: "border-slate-600 bg-slate-800/60 text-slate-300",
    hint: "Variável do backend; mudar exige deploy",
  },
};

export default function ParametersPage() {
  const params = useQuery({ queryKey: ["parameters"], queryFn: getParameters });

  return (
    <div className="space-y-6 p-8">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">Parâmetros</h1>
        <p className="text-sm text-slate-500">
          O que o sistema está usando agora e de onde vem cada valor. Somente leitura.
        </p>
      </header>

      {params.isLoading && <p className="text-sm text-slate-500">Carregando…</p>}
      {params.error && (
        <p className="rounded border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-300">
          Não consegui carregar os parâmetros.
        </p>
      )}

      {params.data?.groups.map((group) => (
        <section
          key={group.title}
          className="rounded-lg border border-slate-800 bg-slate-900/40"
        >
          <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">
            {group.title}
          </h2>
          <dl className="divide-y divide-slate-800/70">
            {group.items.map((item) => (
              <div key={item.key} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <dt className="text-sm text-slate-300">{item.label}</dt>
                  <div className="text-[11px] text-slate-600">{item.key}</div>
                  {item.note && <div className="mt-1 text-xs text-slate-500">{item.note}</div>}
                </div>
                <dd className="text-sm font-medium text-slate-100">{item.value}</dd>
                <span
                  title={SOURCE[item.source].hint}
                  className={`rounded border px-2 py-0.5 text-[10px] uppercase tracking-wide ${SOURCE[item.source].cls}`}
                >
                  {SOURCE[item.source].label}
                </span>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}
