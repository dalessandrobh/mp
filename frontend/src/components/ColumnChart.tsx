import { useState } from "react";

import { niceCeil, useWidth } from "./useWidth";

type Props = {
  title: string;
  dates: string[];
  /** Fração (0.25 = +25%). null = sem dado: nenhuma barra, nunca uma barra de zero. */
  values: (number | null)[];
  formatValue: (v: number) => string;
  formatDate: (iso: string) => string;
  height?: number;
};

const M = { top: 12, right: 16, bottom: 26, left: 58 };
const GAP = 2;
const MAX_BAR = 24;
const R = 4;

// Barra com a ponta de dado arredondada (4px) e a base na linha zero reta.
function barPath(x0: number, x1: number, yBase: number, yEnd: number): string {
  const r = Math.min(R, (x1 - x0) / 2, Math.abs(yEnd - yBase));
  if (yEnd <= yBase) {
    return `M${x0},${yBase} V${yEnd + r} Q${x0},${yEnd} ${x0 + r},${yEnd} H${x1 - r} Q${x1},${yEnd} ${x1},${yEnd + r} V${yBase} Z`;
  }
  return `M${x0},${yBase} V${yEnd - r} Q${x0},${yEnd} ${x0 + r},${yEnd} H${x1 - r} Q${x1},${yEnd} ${x1},${yEnd - r} V${yBase} Z`;
}

export default function ColumnChart({
  title,
  dates,
  values,
  formatValue,
  formatDate,
  height = 180,
}: Props) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const n = dates.length;
  const plotW = width - M.left - M.right;
  const plotH = height - M.top - M.bottom;
  const present = values.filter((v): v is number => v !== null);
  const hi = niceCeil(Math.max(0.01, ...present, 0));
  const lo = -niceCeil(Math.max(0.01, ...present.map((v) => -v), 0));
  const hasNegative = present.some((v) => v < 0);
  const top = hi;
  const bottom = hasNegative ? lo : 0;
  const y = (v: number) => M.top + ((top - v) / (top - bottom)) * plotH;
  const band = n === 0 ? plotW : plotW / n;
  const barW = Math.min(MAX_BAR, band - GAP);
  const cx = (i: number) => M.left + band * i + band / 2;
  const ticks = hasNegative ? [bottom, 0, top] : [0, top / 2, top];
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 70))));
  const tipLeft = hover === null ? 0 : Math.min(Math.max(cx(hover) + 12, 8), width - 150);

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={title}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setHover((h) => Math.min(n - 1, (h ?? -1) + 1));
          if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? n) - 1));
          if (e.key === "Escape") setHover(null);
        }}
        onBlur={() => setHover(null)}
        className="outline-none focus-visible:ring-1 focus-visible:ring-slate-500"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
            <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--chart-muted)">
              {formatValue(t)}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} stroke="var(--chart-axis)" />

        {values.map((v, i) =>
          v === null || v === 0 ? null : (
            <path
              key={dates[i]}
              d={barPath(cx(i) - barW / 2, cx(i) + barW / 2, y(0), y(v))}
              fill={v > 0 ? "var(--series-1)" : "var(--series-neg)"}
              opacity={hover === null || hover === i ? 1 : 0.55}
            />
          ),
        )}

        {dates.map((d, i) =>
          i % labelEvery === 0 ? (
            <text key={d} x={cx(i)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--chart-muted)">
              {formatDate(d)}
            </text>
          ) : null,
        )}

        {/* Alvo de hover = a faixa inteira do dia, bem maior que a barra. */}
        {dates.map((d, i) => (
          <rect
            key={`hit-${d}`}
            x={M.left + band * i}
            y={M.top}
            width={band}
            height={plotH}
            fill="transparent"
            onPointerEnter={() => setHover(i)}
            onPointerLeave={() => setHover(null)}
          />
        ))}
      </svg>

      {hover !== null && (
        <div
          role="status"
          className="pointer-events-none absolute top-2 z-10 w-36 rounded-md border border-slate-700 bg-slate-900 p-2 text-xs shadow-lg"
          style={{ left: tipLeft }}
        >
          <div className="text-slate-400">{formatDate(dates[hover])}</div>
          <strong className="text-slate-100">
            {values[hover] === null ? "sem dado" : formatValue(values[hover] as number)}
          </strong>
        </div>
      )}
    </div>
  );
}
