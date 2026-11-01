// Tile de número. `hero` é o ÚNICO número que lidera uma tela (≥ 48px, mesma sans).
export default function Stat({
  label,
  value,
  hint,
  hero = false,
}: {
  label: string;
  value: string;
  hint?: string;
  hero?: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div
        className={`mt-1 font-semibold text-slate-100 ${hero ? "text-5xl leading-tight" : "text-xl"}`}
      >
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
