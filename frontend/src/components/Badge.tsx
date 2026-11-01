import type { Settlement, Zone } from "../lib/api";

// Cor nunca carrega o significado sozinha: toda pílula traz ícone + rótulo.
// Tons seguem a paleta de status (good/warning/serious/critical) do dataviz.
const ZONES: Record<Zone, { label: string; icon: string; cls: string; hint: string }> = {
  WINNER: {
    label: "Vencedor",
    icon: "▲",
    cls: "border-emerald-700/60 bg-emerald-950/40 text-emerald-300",
    hint: "ROI estável acima do corte, com amostra madura",
  },
  PROMISING: {
    label: "Promissor",
    icon: "↗",
    cls: "border-sky-700/60 bg-sky-950/40 text-sky-300",
    hint: "Tendência positiva, ainda sem amostra para decidir",
  },
  INCONCLUSIVE: {
    label: "Inconclusivo",
    icon: "…",
    cls: "border-slate-600 bg-slate-800/60 text-slate-300",
    hint: "Amostra ou dado ainda imaturo: aguardando, nunca substituído",
  },
  UNDERPERFORMER: {
    label: "Abaixo do esperado",
    icon: "▼",
    cls: "border-red-700/60 bg-red-950/40 text-red-300",
    hint: "ROI negativo com amostra madura e comissão liquidada",
  },
  NO_DATA: {
    label: "Sem dado",
    icon: "∅",
    cls: "border-dashed border-slate-600 bg-transparent text-slate-400",
    hint: "Receita ainda não medida: não é o mesmo que ROI zero",
  },
};

const SETTLEMENTS: Record<Settlement, { label: string; hint: string; cls: string }> = {
  PROVISIONAL: {
    label: "Estimado",
    hint: "Comissão estimada (ConversionReport). Não autoriza corte.",
    cls: "text-amber-300",
  },
  PARTIAL: {
    label: "Parcial",
    hint: "Parte já liquidada, parte ainda estimada.",
    cls: "text-sky-300",
  },
  SETTLED: {
    label: "Liquidado",
    hint: "Comissão final confirmada (ValidatedReport).",
    cls: "text-emerald-300",
  },
};

export function ZoneBadge({ zone }: { zone: Zone }) {
  const z = ZONES[zone];
  return (
    <span
      title={z.hint}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${z.cls}`}
    >
      <span aria-hidden>{z.icon}</span>
      {z.label}
    </span>
  );
}

export function SettlementLabel({ settlement }: { settlement: Settlement }) {
  const s = SETTLEMENTS[settlement];
  return (
    <span title={s.hint} className={`text-xs ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warn" | "info" }) {
  const cls = {
    neutral: "border-slate-700 bg-slate-800/60 text-slate-300",
    warn: "border-amber-700/60 bg-amber-950/40 text-amber-300",
    info: "border-sky-700/60 bg-sky-950/40 text-sky-300",
  }[tone];
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${cls}`}>{children}</span>;
}
