/**
 * Motor do simulador de bomba de calor para piscina.
 *
 * Funções puras: nada aqui toca no DOM. O arquivo `test/engine.test.mjs`
 * exercita cada bloco isoladamente.
 *
 * As hipóteses e a origem de cada correlação estão no README da pasta.
 */

import { CURVE_TEMPS, CURVE_WATER_OUT, RATING_WATER_OUT, BREAKER_SIZES } from './data.js';

export const ATM_SEA_KPA = 101.325;
export const LATENT_HEAT_KJ_KG = 2430; // calor latente de vaporização a ~30 °C
export const CP_WATER_KJ_KGK = 4.186;
export const WATER_DENSITY_KG_M3 = 1000;

/** Energia para elevar 1 m³ de água em 1 °C, em kWh. */
export const KWH_PER_M3_K = (WATER_DENSITY_KG_M3 * CP_WATER_KJ_KGK) / 3600; // ≈ 1,163

/** Fração das perdas de superfície atribuída à condução por paredes e fundo. */
export const CONDUCTION_FRACTION = 0.03;

/** Emissividade da água e constante de Stefan-Boltzmann. */
const EMISSIVITY = 0.95;
const SIGMA = 5.67e-8;

/** Céu limpo noturno: temperatura aparente abaixo da do ar, em K. */
const SKY_DROP_K = 10;

/** Horas de sol por dia consideradas no ganho solar. */
export const DAYLIGHT_HOURS = 11;

/** Absortividade efetiva da lâmina d'água à radiação solar. */
export const SOLAR_ABSORPTANCE = 0.85;

// ---------------------------------------------------------------- psicrometria

/** Pressão de vapor saturado (Magnus-Tetens), em kPa. */
export function saturationPressureKPa(tC) {
  return 0.61094 * Math.exp((17.625 * tC) / (tC + 243.04));
}

/** Pressão atmosférica pela altitude (atmosfera padrão), em kPa. */
export function atmPressureKPa(altitudeM = 0) {
  return ATM_SEA_KPA * Math.pow(1 - 2.25577e-5 * altitudeM, 5.25588);
}

/** Razão de umidade (kg de vapor / kg de ar seco). */
export function humidityRatio(pvKPa, patmKPa) {
  const pv = Math.min(Math.max(pvKPa, 0), patmKPa - 0.01);
  return (0.622 * pv) / (patmKPa - pv);
}

// ----------------------------------------------------------------- geometria

/**
 * Área de espelho d'água [m²] e volume [m³] a partir da forma escolhida.
 * `depth` é a profundidade MÉDIA.
 */
export function poolGeometry(input) {
  const { shape } = input;
  const depth = num(input.depth);
  let area;
  if (shape === 'round') {
    const d = num(input.diameter);
    area = (Math.PI * d * d) / 4;
  } else if (shape === 'oval') {
    area = (Math.PI * num(input.length) * num(input.width)) / 4;
  } else if (shape === 'custom') {
    return { area: num(input.area), volume: num(input.volume) };
  } else {
    area = num(input.length) * num(input.width);
  }
  return { area, volume: area * depth };
}

// ------------------------------------------------------------ perdas térmicas

/**
 * Perdas pela superfície, em W/m², decompostas por mecanismo.
 *
 * evaporação — m = (25 + 19·v)·(x_água − x_ar), correlação de camada limite
 *              sobre lâmina d'água (VDI 2089 / Bernier), convertida em fluxo
 *              de calor pelo calor latente.
 * convecção  — h = 3,1 + 4,1·v  [W/m²·K]
 * radiação   — corpo cinza contra o céu (externa) ou contra o ambiente (coberta)
 */
export function surfaceLoss({
  tWater,
  tAir,
  rh,
  wind,
  altitude = 0,
  outdoor = true,
  cover = null,
}) {
  const patm = atmPressureKPa(altitude);
  const xWater = humidityRatio(saturationPressureKPa(tWater), patm);
  const xAir = humidityRatio((rh / 100) * saturationPressureKPa(tAir), patm);

  const beta = 25 + 19 * wind; // kg/(m²·h)
  let evaporation = (Math.max(0, beta * (xWater - xAir)) * LATENT_HEAT_KJ_KG) / 3.6;
  let convection = (3.1 + 4.1 * wind) * (tWater - tAir);

  const tSurr = outdoor ? tAir - SKY_DROP_K : tAir;
  let radiation =
    EMISSIVITY * SIGMA * (Math.pow(tWater + 273.15, 4) - Math.pow(tSurr + 273.15, 4));

  if (cover) {
    evaporation *= cover.evap;
    convection *= cover.conv;
    radiation *= cover.rad;
  }

  const surface = evaporation + convection + radiation;
  const conduction = surface * CONDUCTION_FRACTION;
  return {
    evaporation,
    convection,
    radiation,
    conduction,
    total: surface + conduction,
  };
}

/** Mesma decomposição, já multiplicada pela área e convertida para kW. */
export function poolLoad(params, areaM2) {
  const w = surfaceLoss(params);
  const scale = areaM2 / 1000;
  return {
    evaporation: w.evaporation * scale,
    convection: w.convection * scale,
    radiation: w.radiation * scale,
    conduction: w.conduction * scale,
    total: w.total * scale,
    perM2: w.total,
  };
}

// ------------------------------------------------------- desempenho do equipamento

/** Interpolação linear com extrapolação travada nos extremos. */
export function interp(xs, ys, x) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  for (let i = 1; i < xs.length; i += 1) {
    if (x <= xs[i]) {
      const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
      return ys[i - 1] + t * (ys[i] - ys[i - 1]);
    }
  }
  return ys[ys.length - 1];
}

/**
 * Correção de capacidade pela temperatura da água.
 *
 * A curva do catálogo é levantada com água saindo a 35 °C. Comparando-a com a
 * tabela de 26 °C/80% UR (água saindo a 28 °C) o próprio catálogo mostra ~1% de
 * capacidade a mais por °C a menos na saída de água — é esse o coeficiente.
 */
export const CAPACITY_PER_K = 0.010;

/** Acréscimo de potência absorvida por °C a mais na saída de água. */
export const POWER_PER_K = 0.012;

/** Capacidade de aquecimento [kW] na temperatura de ar e de água informadas. */
export function capacityAt(model, tAir, tWaterOut) {
  const base = interp(CURVE_TEMPS, model.curve, tAir);
  return base * (1 - CAPACITY_PER_K * (tWaterOut - CURVE_WATER_OUT));
}

/** Potência elétrica absorvida em frequência máxima [kW]. */
export function inputPowerFull(model, tWaterOut) {
  return model.heat80.powMax * (1 + POWER_PER_K * (tWaterOut - RATING_WATER_OUT));
}

/** COP em frequência máxima. */
export function copFull(model, tAir, tWaterOut) {
  return capacityAt(model, tAir, tWaterOut) / inputPowerFull(model, tWaterOut);
}

/**
 * COP na carga pedida, aproveitando a modulação do inversor.
 *
 * O ganho entre frequência mínima e máxima é o do próprio catálogo
 * (copMax/copMin = 15,8/6,8 ≈ 2,3). Abaixo da capacidade mínima o compressor
 * liga e desliga, e aplicamos 8% de penalidade de ciclagem.
 */
export function copAt(model, tAir, tWaterOut, loadKw) {
  const qMax = capacityAt(model, tAir, tWaterOut);
  const ratioMin = model.heat80.capMin / model.heat80.capMax;
  const qMin = qMax * ratioMin;
  const gain = model.heat80.copMax / model.heat80.copMin;
  const full = copFull(model, tAir, tWaterOut);
  if (loadKw >= qMax) return full;
  if (loadKw <= qMin) return full * gain * 0.92;
  const r = loadKw / qMax;
  return full * (1 + (gain - 1) * ((1 - r) / (1 - ratioMin)));
}

/** Disjuntor comercial sugerido: 1,25 × corrente máxima (NBR 5410). */
export function suggestedBreakerA(model) {
  const target = model.maxCurrentA * 1.25;
  return BREAKER_SIZES.find((a) => a >= target) ?? BREAKER_SIZES[BREAKER_SIZES.length - 1];
}

// --------------------------------------------------------------- simulação

function num(v) {
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
}

/**
 * Roda o dimensionamento completo.
 *
 * Entradas (todas em SI, temperaturas em °C):
 *   area, volume        — geometria já resolvida
 *   tTarget             — temperatura desejada da água
 *   tStart              — temperatura atual da água (aquecimento inicial)
 *   tAir, rh, altitude  — ar externo no período de projeto
 *   wind, outdoor       — exposição
 *   cover, coverHours   — cobertura térmica e horas por dia com ela fechada
 *   solar, useSolar     — irradiação [kWh/m²/dia] e se entra no balanço
 *   runHours            — horas de funcionamento por dia (junto com a filtragem)
 *   heatUpHours         — prazo desejado para o aquecimento inicial
 *   tariff              — R$/kWh
 *   models              — catálogo
 */
export function simulate(input) {
  const area = num(input.area);
  const volume = num(input.volume);
  const tTarget = num(input.tTarget);
  const tStart = num(input.tStart);
  const tAir = num(input.tAir);
  const runHours = Math.min(24, Math.max(1, num(input.runHours)));
  const heatUpHours = Math.max(1, num(input.heatUpHours));
  const tariff = num(input.tariff);
  const cover = input.cover && input.cover.id !== 'none' ? input.cover : null;
  const coverHours = cover ? Math.min(24, Math.max(0, num(input.coverHours))) : 0;
  const openHours = 24 - coverHours;

  // Temperatura da água na saída do trocador durante o regime (ΔT ~ 2 °C).
  const tWaterOut = tTarget + 1;

  const base = {
    tAir,
    rh: num(input.rh),
    wind: num(input.wind),
    altitude: num(input.altitude),
    outdoor: input.outdoor !== false,
  };

  // Regime permanente, piscina descoberta — é a condição de dimensionamento.
  const openLoad = poolLoad({ ...base, tWater: tTarget, cover: null }, area);
  // Mesma condição com a capa fechada.
  const coveredLoad = cover
    ? poolLoad({ ...base, tWater: tTarget, cover }, area)
    : openLoad;

  // Perda média ponderada pelo uso real da capa, em kWh térmicos por dia.
  const dailyLossKwh = (openLoad.total * openHours + coveredLoad.total * coverHours);

  // Ganho solar: só conta nas horas de sol, atenuado quando a capa está fechada.
  const openDaylight = Math.min(openHours, DAYLIGHT_HOURS);
  const coveredDaylight = DAYLIGHT_HOURS - openDaylight;
  const coverSolar = cover ? cover.solar : 1;
  const solarKwh = input.useSolar
    ? num(input.solar) *
      area *
      SOLAR_ABSORPTANCE *
      ((openDaylight + coveredDaylight * coverSolar) / DAYLIGHT_HOURS)
    : 0;

  const netDailyKwh = Math.max(0, dailyLossKwh - solarKwh);

  // Aquecimento inicial: energia sensível + perdas médias durante a subida.
  const heatUpKwh = KWH_PER_M3_K * volume * Math.max(0, tTarget - tStart);
  const tMid = (tStart + tTarget) / 2;
  const midLoad = cover
    ? (poolLoad({ ...base, tWater: tMid, cover: null }, area).total * openHours +
        poolLoad({ ...base, tWater: tMid, cover }, area).total * coverHours) / 24
    : poolLoad({ ...base, tWater: tMid, cover: null }, area).total;

  // A máquina precisa atender ao mais exigente de dois deveres:
  //  (a) repor a energia do dia dentro da janela de funcionamento;
  //  (b) cumprir o aquecimento inicial no prazo pedido, operando contínuo.
  const dutyDaily = netDailyKwh / runHours;
  const dutyHeatUp = heatUpKwh / heatUpHours + midLoad;
  const requiredKw = Math.max(dutyDaily, dutyHeatUp);

  const rows = (input.models || []).map((model) => {
    const capacity = capacityAt(model, tAir, tWaterOut);
    const qMin = capacity * (model.heat80.capMin / model.heat80.capMax);

    // Aquecimento inicial em operação contínua.
    const netHeatKw = capacity - midLoad;
    const heatUpRealHours = netHeatKw > 0 ? heatUpKwh / netHeatKw : Infinity;

    // Regime: precisa entregar netDailyKwh dentro das horas disponíveis.
    const neededKw = netDailyKwh / runHours;
    const keepsUp = neededKw <= capacity;
    const loadKw = Math.min(neededKw, capacity);
    const cop = copAt(model, tAir, tWaterOut, loadKw);
    const minHours = capacity > 0 ? netDailyKwh / capacity : Infinity;
    const cyclesShort = loadKw < qMin;

    // Se o equipamento não repõe a perda dentro da janela, a piscina nunca
    // chega à temperatura pedida: consumo e custo desse cenário não existem.
    const elecKwhDay = keepsUp && cop > 0 ? netDailyKwh / cop : NaN;
    const costDay = elecKwhDay * tariff;
    const deliveredKwhDay = capacity * runHours;

    return {
      model,
      capacity,
      minCapacity: qMin,
      cop,
      loadKw: neededKw,
      keepsUp,
      cyclesShort,
      minHours,
      heatUpHours: heatUpRealHours,
      heatUpDays: heatUpRealHours / runHours,
      elecKwhDay,
      costDay,
      costMonth: costDay * 30,
      deliveredKwhDay,
      sufficient: capacity >= requiredKw && keepsUp,
      margin: requiredKw > 0 ? capacity / requiredKw : Infinity,
    };
  });

  const recommended = rows.find((r) => r.sufficient) || null;
  const fallback = recommended || rows[rows.length - 1] || null;

  return {
    area,
    volume,
    tWaterOut,
    requiredKw,
    dutyDaily,
    dutyHeatUp,
    maintenanceKw: openLoad.total,
    coveredMaintenanceKw: coveredLoad.total,
    heatUpKwh,
    dailyLossKwh,
    solarKwh,
    netDailyKwh,
    breakdown: openLoad,
    coveredBreakdown: coveredLoad,
    rows,
    recommended,
    selected: fallback,
    coverHours,
    runHours,
  };
}

export { num };
