import { useEffect, useRef, useState } from "react";

/** Largura atual do elemento: o SVG redesenha em px reais, sem distorcer texto. */
export function useWidth<T extends HTMLElement>(initial = 720) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(initial);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

/** Teto "redondo" para o eixo: 1, 2, 2.5, 5 × 10ⁿ. */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const exp = Math.floor(Math.log10(value));
  const base = 10 ** exp;
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (value <= m * base) return m * base;
  }
  return 10 * base;
}

/** Eixo de 0 até um máximo redondo, com degraus redondos (1, 2 ou 5 × 10ⁿ) e 3–6 marcas. */
export function niceAxis(value: number): { max: number; ticks: number[] } {
  const raw = Math.max(value, Number.EPSILON);
  const exp = Math.floor(Math.log10(raw / 4));
  const base = 10 ** exp;
  const step = [1, 2, 5, 10].map((m) => m * base).find((s) => raw / s <= 5) ?? 10 * base;
  const count = Math.ceil(raw / step - 1e-9);
  return { max: step * count, ticks: Array.from({ length: count + 1 }, (_, i) => step * i) };
}
