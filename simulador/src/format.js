/** Formatação pt-BR compartilhada pela interface. */

export function fmt(value, decimals = 1) {
  if (!Number.isFinite(value)) return '—';
  return value.toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function money(value) {
  if (!Number.isFinite(value)) return '—';
  return value.toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  });
}

/** Horas → "3 h 20 min" ou "2 dias 4 h". */
export function duration(hours) {
  if (!Number.isFinite(hours)) return 'não atinge';
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) {
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const d = Math.floor(hours / 24);
  const h = Math.round(hours - d * 24);
  return h ? `${d} dias ${h} h` : `${d} dias`;
}
