import { useState } from "react";

import { niceAxis, useWidth } from "./useWidth";

export type Series = {
  key: string;
  label: string;
  color: string;
  /** null = sem dado naquele dia: a linha QUEBRA, nunca desce a zero. */
  values: (number | null)[];
};

type Props = {
  title: string;
  dates: string[];
  series: Series[];
  /** true nos dias cujo dado ainda não liquidou (sombreados). */
  shaded: boolean[];
  formatValue: (v: number) => string;
  formatAxis: (v: number) => string;
  formatDate: (iso: string) => string;
  height?: number;
};

const M = { top: 12, right: 92, bottom: 26, left: 58 };

export default function LineChart({
  title,
  dates,
  series,
  shaded,
  formatValue,
  formatAxis,
  formatDate,
  height = 260,
}: Props) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const n = dates.length;
  const plotW = width - M.left - M.right;
  const plotH = height - M.top - M.bottom;
  const all = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const { max, ticks } = niceAxis(Math.max(0, ...all));
  const x = (i: number) => M.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => M.top + plotH - (v / max) * plotH;
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 70))));

  // Segmentos contíguos de dado: um buraco no meio parte a linha em duas.
  const segments = (values: (number | null)[]) => {
    const out: [number, number][][] = [];
    let current: [number, number][] = [];
    values.forEach((v, i) => {
      if (v === null) {
        if (current.length) out.push(current);
        current = [];
      } else current.push([i, v]);
    });
    if (current.length) out.push(current);
    return out;
  };

  const shadeRuns: [number, number][] = [];
  shaded.forEach((on, i) => {
    if (!on) return;
    const last = shadeRuns[shadeRuns.length - 1];
    if (last && last[1] === i - 1) last[1] = i;
    else shadeRuns.push([i, i]);
  });
  const step = n <= 1 ? plotW : plotW / (n - 1);

  const move = (clientX: number, rect: DOMRect) => {
    const i = Math.round(((clientX - rect.left - M.left) / plotW) * (n - 1));
    setHover(n === 0 ? null : Math.min(n - 1, Math.max(0, i)));
  };

  // Rótulo direto no fim de cada linha — mas só quando não colide com o de cima;
  // empurrar rótulos para o lado descola do dado, e a legenda já carrega a identidade.
  const endLabels: { s: Series; i: number; yy: number }[] = [];
  series.forEach((s) => {
    const i = s.values.reduce<number>((acc, v, idx) => (v !== null ? idx : acc), -1);
    if (i >= 0) endLabels.push({ s, i, yy: y(s.values[i] as number) });
  });
  const shown = endLabels
    .sort((a, b) => a.yy - b.yy)
    .filter((l, idx, arr) => idx === 0 || l.yy - arr[idx - 1].yy >= 16);

  const tipLeft = hover === null ? 0 : Math.min(Math.max(x(hover) + 12, 8), width - 190);

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={title}
        tabIndex={0}
        onPointerMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setHover((h) => Math.min(n - 1, (h ?? -1) + 1));
          if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? n) - 1));
          if (e.key === "Escape") setHover(null);
        }}
        className="outline-none focus-visible:ring-1 focus-visible:ring-slate-500"
      >
        {shadeRuns.map(([a, b]) => (
          <rect
            key={a}
            x={Math.max(M.left, x(a) - step / 2)}
            y={M.top}
            width={Math.min(width - M.right, x(b) + step / 2) - Math.max(M.left, x(a) - step / 2)}
            height={plotH}
            fill="var(--chart-shade)"
          />
        ))}

        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
            <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--chart-muted)">
              {formatAxis(t)}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} stroke="var(--chart-axis)" />

        {dates.map((d, i) =>
          i % labelEvery === 0 ? (
            <text key={d} x={x(i)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--chart-muted)">
              {formatDate(d)}
            </text>
          ) : null,
        )}

        {series.map((s) =>
          segments(s.values).map((seg, k) =>
            seg.length === 1 ? (
              // Dia isolado entre buracos: sem vizinho não há linha, então vira ponto.
              <circle key={`${s.key}-${k}`} cx={x(seg[0][0])} cy={y(seg[0][1])} r={4} fill={s.color} />
            ) : (
              <polyline
                key={`${s.key}-${k}`}
                points={seg.map(([i, v]) => `${x(i)},${y(v)}`).join(" ")}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ),
          ),
        )}

        {shown.map(({ s, i, yy }) => (
          <g key={s.key}>
            <circle cx={x(i)} cy={yy} r={4} fill={s.color} stroke="var(--chart-surface)" strokeWidth={2} />
            <text x={x(i) + 10} y={yy + 4} fontSize={12} fill="#cbd5e1">
              {s.label}
            </text>
          </g>
        ))}

        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + plotH} stroke="var(--chart-axis)" />
            {series.map((s) => {
              const v = s.values[hover];
              return v === null ? null : (
                <circle
                  key={s.key}
                  cx={x(hover)}
                  cy={y(v)}
                  r={4}
                  fill={s.color}
                  stroke="var(--chart-surface)"
                  strokeWidth={2}
                />
              );
            })}
          </g>
        )}
      </svg>

      {hover !== null && (
        <div
          role="status"
          className="pointer-events-none absolute top-2 z-10 w-44 rounded-md border border-slate-700 bg-slate-900 p-2 text-xs shadow-lg"
          style={{ left: tipLeft }}
        >
          <div className="mb-1 text-slate-400">
            {formatDate(dates[hover])}
            {shaded[hover] && " · estimado"}
          </div>
          {series.map((s) => (
            <div key={s.key} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-slate-400">
                <span className="inline-block h-0.5 w-3" style={{ background: s.color }} />
                {s.label}
              </span>
              <strong className="text-slate-100">
                {s.values[hover] === null ? "sem dado" : formatValue(s.values[hover] as number)}
              </strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
