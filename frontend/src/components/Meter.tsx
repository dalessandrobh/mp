import { num } from "../lib/format";

// Medidor de orçamento: o preenchimento carrega a severidade (acento → alerta → perigo);
// a trilha é um passo mais claro da mesma rampa, para o estado ler na barra inteira.
export default function Meter({ used, cap, label }: { used: string; cap: string; label: string }) {
  const usedN = num(used) ?? 0;
  const capN = num(cap) ?? 0;
  const ratio = capN > 0 ? Math.min(1, usedN / capN) : 0;
  const fill = ratio >= 0.95 ? "bg-red-500" : ratio >= 0.8 ? "bg-amber-400" : "bg-sky-500";

  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={capN} aria-valuenow={usedN}>
      <div className="h-2 overflow-hidden rounded-full bg-sky-950">
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
