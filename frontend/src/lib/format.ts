// Formatação pt-BR. Valor ausente vira "—" e NUNCA zero: sem dado não é R$ 0,00.
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const INT = new Intl.NumberFormat("pt-BR");
const PCT = new Intl.NumberFormat("pt-BR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: "exceptZero",
});
const DATE = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });
const DATETIME = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export const MISSING = "—";

export function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export const money = (v: string | number | null | undefined) => {
  const n = num(v);
  return n === null ? MISSING : BRL.format(n);
};

export const integer = (v: string | number | null | undefined) => {
  const n = num(v);
  return n === null ? MISSING : INT.format(n);
};

/** ROI chega como fração (0.25 = +25%). */
export const roiPct = (v: string | number | null | undefined) => {
  const n = num(v);
  return n === null ? MISSING : PCT.format(n);
};

// Datas "YYYY-MM-DD" são dia de calendário, não instante: ancorar ao meio-dia evita que
// o fuso empurre a data para o dia anterior.
export const shortDate = (iso: string) => DATE.format(new Date(`${iso.slice(0, 10)}T12:00:00`));
export const dateTime = (iso: string) => DATETIME.format(new Date(iso));

/** Taxa em fração (0.085) -> "8,5%". */
export const ratePct = (v: string | number | null | undefined) => {
  const n = num(v);
  return n === null ? MISSING : `${(n * 100).toFixed(1).replace(".", ",")}%`;
};

export const score = (v: string | number | null | undefined) => {
  const n = num(v);
  return n === null ? MISSING : n.toFixed(1).replace(".", ",");
};
