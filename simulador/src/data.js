/**
 * Ficha técnica da linha ECOPOOL (bomba de calor / trocador para piscina).
 *
 * Todos os números vêm do catálogo do fabricante:
 *   - seção "2 Ficha Técnica"
 *   - seção "2.1 Capacidade de aquecimento"
 *   - tabela "CURVA DE AQUECIMENTO — Água entrando a 33 °C, água saindo a 35 °C"
 *
 * Convenção das faixas do catálogo ("7.6~1.7"): o primeiro valor é o compressor
 * na frequência máxima, o segundo é a frequência mínima. Por isso
 * capMax/powMax = copMin e capMin/powMin = copMax (o COP alto é o de baixa
 * frequência, como a própria nota de rodapé do catálogo explica).
 */

/** Temperaturas de bulbo seco da curva de aquecimento, em °C. */
export const CURVE_TEMPS = [-10, -5, 0, 10, 15, 20, 25, 30, 35, 40, 43];

/** Condição de referência da curva: água entrando a 33 °C, saindo a 35 °C. */
export const CURVE_WATER_OUT = 35;

/** Condição de referência do COP nominal: ar 26 °C / 80% UR, água 26 → 28 °C. */
export const RATING_AIR = 26;
export const RATING_WATER_OUT = 28;

export const MODELS = [
  {
    id: 'ecopool-7',
    name: 'ECOPOOL 7',
    nominalKw: 7,
    btuH: 25000,
    maxInputKw: 1.6,
    maxCurrentA: 7.3,
    airFlowM3h: 2500,
    waterFlowM3h: 2.5,
    refrigerant: 'R32',
    chargeG: 380,
    noise1m: [39, 49],
    noise10m: [20, 29],
    weightNetKg: 42,
    weightGrossKg: 53,
    dimNetMm: '864 × 349 × 592',
    dimPackedMm: '930 × 400 × 640',
    heat80: { capMax: 7.6, capMin: 1.7, powMax: 1.12, powMin: 0.11, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 6.1, capMin: 1.4, powMax: 1.24, powMin: 0.18, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 4.2, capMin: 1.0, powMax: 1.11, powMin: 0.15, copMax: 6.7, copMin: 3.8 },
    curve: [3.01, 3.57, 4.13, 5.25, 5.73, 6.37, 6.94, 7.50, 8.06, 8.62, 8.94],
  },
  {
    id: 'ecopool-10',
    name: 'ECOPOOL 10',
    nominalKw: 10,
    btuH: 35000,
    maxInputKw: 1.8,
    maxCurrentA: 8.3,
    airFlowM3h: 2500,
    waterFlowM3h: 3.5,
    refrigerant: 'R32',
    chargeG: 460,
    noise1m: [40, 52],
    noise10m: [20, 32],
    weightNetKg: 43,
    weightGrossKg: 54,
    dimNetMm: '864 × 349 × 592',
    dimPackedMm: '930 × 400 × 640',
    heat80: { capMax: 9.5, capMin: 2.3, powMax: 1.4, powMin: 0.15, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 7.6, capMin: 1.9, powMax: 1.55, powMin: 0.25, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 5.3, capMin: 1.3, powMax: 1.4, powMin: 0.19, copMax: 6.7, copMin: 3.8 },
    curve: [3.88, 4.60, 5.32, 6.76, 7.37, 8.20, 8.93, 9.65, 10.37, 11.09, 11.51],
  },
  {
    id: 'ecopool-13',
    name: 'ECOPOOL 13',
    nominalKw: 13,
    btuH: 45000,
    maxInputKw: 2.2,
    maxCurrentA: 10.2,
    airFlowM3h: 3300,
    waterFlowM3h: 4.5,
    refrigerant: 'R32',
    chargeG: 850,
    noise1m: [42, 53],
    noise10m: [22, 33],
    weightNetKg: 53,
    weightGrossKg: 64,
    dimNetMm: '925 × 364 × 642',
    dimPackedMm: '990 × 435 × 760',
    heat80: { capMax: 13.2, capMin: 3.0, powMax: 1.91, powMin: 0.19, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 9.8, capMin: 2.3, powMax: 1.96, powMin: 0.3, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 7.2, capMin: 1.7, powMax: 1.89, powMin: 0.25, copMax: 6.7, copMin: 3.8 },
    curve: [5.31, 6.29, 7.28, 9.25, 10.09, 11.23, 12.21, 13.20, 14.19, 15.17, 15.75],
  },
  {
    id: 'ecopool-17',
    name: 'ECOPOOL 17',
    nominalKw: 17,
    btuH: 60000,
    maxInputKw: 2.6,
    maxCurrentA: 12,
    airFlowM3h: 3300,
    waterFlowM3h: 5.5,
    refrigerant: 'R32',
    chargeG: 850,
    noise1m: [43, 55],
    noise10m: [23, 35],
    weightNetKg: 54,
    weightGrossKg: 65,
    dimNetMm: '925 × 364 × 642',
    dimPackedMm: '990 × 435 × 760',
    heat80: { capMax: 17.3, capMin: 3.8, powMax: 2.5, powMin: 0.24, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 13.5, capMin: 3.0, powMax: 2.76, powMin: 0.39, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 9.4, capMin: 2.1, powMax: 2.47, powMin: 0.31, copMax: 6.7, copMin: 3.8 },
    curve: [6.94, 8.23, 9.52, 12.10, 13.19, 14.68, 15.97, 17.26, 18.55, 19.84, 20.60],
  },
  {
    id: 'ecopool-21',
    name: 'ECOPOOL 21',
    nominalKw: 21,
    btuH: 75000,
    maxInputKw: 3.2,
    maxCurrentA: 14.7,
    airFlowM3h: 3300,
    waterFlowM3h: 6.5,
    refrigerant: 'R32',
    chargeG: 950,
    noise1m: [45, 56],
    noise10m: [25, 36],
    weightNetKg: 58,
    weightGrossKg: 69,
    dimNetMm: '925 × 364 × 642',
    dimPackedMm: '990 × 435 × 760',
    heat80: { capMax: 21.1, capMin: 4.8, powMax: 3.09, powMin: 0.3, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 16.5, capMin: 3.8, powMax: 3.37, powMin: 0.5, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 11.6, capMin: 2.7, powMax: 3.05, powMin: 0.4, copMax: 6.7, copMin: 3.8 },
    curve: [8.57, 10.17, 11.76, 14.95, 16.29, 18.14, 19.73, 21.32, 22.92, 24.51, 25.45],
  },
  {
    id: 'ecopool-28',
    name: 'ECOPOOL 28',
    nominalKw: 28,
    btuH: 100000,
    maxInputKw: 4.5,
    maxCurrentA: 20.4,
    airFlowM3h: 5000,
    waterFlowM3h: 9,
    refrigerant: 'R32',
    chargeG: 1170,
    noise1m: [47, 58],
    noise10m: [27, 38],
    weightNetKg: 86,
    weightGrossKg: 99,
    dimNetMm: '1084 × 399 × 737',
    dimPackedMm: '1146 × 460 × 862',
    heat80: { capMax: 28.2, capMin: 6.8, powMax: 4.12, powMin: 0.43, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 23.1, capMin: 5.5, powMax: 4.7, powMin: 0.72, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 14.9, capMin: 3.8, powMax: 3.92, powMin: 0.57, copMax: 6.7, copMin: 3.8 },
    curve: [11.43, 13.56, 15.68, 19.93, 21.73, 24.18, 26.31, 28.43, 30.56, 32.68, 33.93],
  },
  {
    id: 'ecopool-35',
    name: 'ECOPOOL 35',
    nominalKw: 35,
    btuH: 120000,
    maxInputKw: 4.8,
    maxCurrentA: 30,
    airFlowM3h: 5000,
    waterFlowM3h: 12,
    refrigerant: 'R32',
    chargeG: 1300,
    noise1m: [49, 59],
    noise10m: [29, 39],
    weightNetKg: 98,
    weightGrossKg: 110,
    dimNetMm: '1084 × 399 × 737',
    dimPackedMm: '1146 × 460 × 862',
    heat80: { capMax: 35.3, capMin: 8.8, powMax: 5.15, powMin: 0.56, copMax: 15.8, copMin: 6.8 },
    heat70: { capMax: 25.5, capMin: 6.4, powMax: 5.2, powMin: 0.84, copMax: 7.6, copMin: 4.9 },
    cool: { capMax: 19.3, capMin: 4.9, powMax: 5.08, powMin: 0.73, copMax: 6.7, copMin: 3.8 },
    curve: [14.29, 16.94, 19.60, 24.91, 27.16, 30.23, 32.88, 35.54, 38.20, 40.85, 42.41],
  },
];

/** Características comuns a toda a linha (ficha técnica). */
export const COMMON_SPECS = {
  heatExchanger: 'Titânio',
  airFlowDirection: 'Horizontal',
  defrost: 'Válvula de 4 vias',
  casing: 'ABS',
  evaporatorFins: 'Alumínio',
  internalPiping: 'Cobre',
  ingressProtection: 'IPX4',
  supply: '220~240 V / 50 (60 Hz)',
  pressureMpa: '0,2 / 4,4',
};

/** Disjuntores comerciais (A) para a sugestão de proteção. */
export const BREAKER_SIZES = [10, 16, 20, 25, 32, 40, 50, 63, 80];
