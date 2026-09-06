type Tone = "ok" | "warn" | "danger" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "border-emerald-800/60 bg-emerald-950/30 text-emerald-300",
  warn: "border-amber-800/60 bg-amber-950/30 text-amber-300",
  danger: "border-red-800/60 bg-red-950/30 text-red-300",
  neutral: "border-slate-800 bg-slate-900/50 text-slate-300",
};

export default function StatusCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
}) {
  return (
    <div className={`rounded-lg border p-4 ${TONE_CLASSES[tone]}`}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs opacity-70">{hint}</div>}
    </div>
  );
}
