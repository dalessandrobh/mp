import test from 'node:test';
import assert from 'node:assert/strict';

import { MODELS, CURVE_TEMPS } from '../src/data.js';
import {
  atmPressureKPa,
  capacityAt,
  copAt,
  copFull,
  humidityRatio,
  interp,
  KWH_PER_M3_K,
  poolGeometry,
  poolLoad,
  saturationPressureKPa,
  simulate,
  suggestedBreakerA,
  surfaceLoss,
} from '../src/engine.js';
import { COVER_TYPES } from '../src/climate.js';

const close = (a, b, tol, msg) =>
  assert.ok(Math.abs(a - b) <= tol, `${msg ?? ''} esperado ~${b}, obtido ${a}`);

test('pressão de vapor saturado bate com a tabela', () => {
  close(saturationPressureKPa(0), 0.611, 0.005, '0 °C');
  close(saturationPressureKPa(20), 2.339, 0.02, '20 °C');
  close(saturationPressureKPa(28), 3.782, 0.03, '28 °C');
  close(saturationPressureKPa(40), 7.384, 0.05, '40 °C');
});

test('pressão atmosférica cai com a altitude', () => {
  close(atmPressureKPa(0), 101.325, 0.01, 'nível do mar');
  close(atmPressureKPa(1000), 89.87, 0.3, '1000 m');
  assert.ok(atmPressureKPa(1100) < atmPressureKPa(760));
});

test('razão de umidade do ar saturado a 28 °C', () => {
  const x = humidityRatio(saturationPressureKPa(28), 101.325);
  close(x, 0.0241, 0.0005);
});

test('interpolação linear respeita os nós e trava nas pontas', () => {
  const ys = MODELS[0].curve;
  assert.equal(interp(CURVE_TEMPS, ys, 25), 6.94);
  assert.equal(interp(CURVE_TEMPS, ys, -30), ys[0]);
  assert.equal(interp(CURVE_TEMPS, ys, 60), ys[ys.length - 1]);
  close(interp(CURVE_TEMPS, ys, 27.5), (6.94 + 7.5) / 2, 1e-9);
});

test('geometria das formas de piscina', () => {
  const ret = poolGeometry({ shape: 'rect', length: 8, width: 4, depth: 1.4 });
  assert.equal(ret.area, 32);
  close(ret.volume, 44.8, 1e-9);

  const round = poolGeometry({ shape: 'round', diameter: 4, depth: 1.2 });
  close(round.area, Math.PI * 4, 1e-9);

  const custom = poolGeometry({ shape: 'custom', area: 30, volume: 40 });
  assert.deepEqual(custom, { area: 30, volume: 40 });
});

test('perdas de superfície ficam na ordem de grandeza conhecida', () => {
  // Piscina externa a 28 °C, ar 26 °C / 70% UR, brisa leve.
  const l = surfaceLoss({ tWater: 28, tAir: 26, rh: 70, wind: 1, outdoor: true });
  assert.ok(l.evaporation > 200 && l.evaporation < 350, `evaporação ${l.evaporation}`);
  assert.ok(l.radiation > 40 && l.radiation < 90, `radiação ${l.radiation}`);
  // A evaporação é o mecanismo dominante em piscina descoberta.
  assert.ok(l.evaporation / l.total > 0.55);
});

test('a capa térmica corta a maior parte da perda', () => {
  const params = { tWater: 28, tAir: 18, rh: 70, wind: 1.2, outdoor: true };
  const open = surfaceLoss(params);
  const covered = surfaceLoss({ ...params, cover: COVER_TYPES[1] });
  assert.ok(covered.total / open.total < 0.3, `redução ${covered.total / open.total}`);
});

test('ar mais frio e mais seco aumenta a perda', () => {
  const warm = surfaceLoss({ tWater: 28, tAir: 24, rh: 80, wind: 1 });
  const cold = surfaceLoss({ tWater: 28, tAir: 14, rh: 80, wind: 1 });
  const dry = surfaceLoss({ tWater: 28, tAir: 24, rh: 40, wind: 1 });
  assert.ok(cold.total > warm.total);
  assert.ok(dry.total > warm.total);
});

test('capacidade reproduz a curva do catálogo na condição da curva', () => {
  for (const model of MODELS) {
    close(capacityAt(model, 25, 35), model.curve[6], 1e-9, model.name);
  }
});

test('capacidade cresce com o ar quente e cai com a água quente', () => {
  const m = MODELS[3];
  assert.ok(capacityAt(m, 30, 30) > capacityAt(m, 10, 30));
  assert.ok(capacityAt(m, 25, 30) > capacityAt(m, 25, 38));
});

test('COP de catálogo é reproduzido na condição nominal', () => {
  for (const model of MODELS) {
    // Ar 26 °C, água saindo a 28 °C → o catálogo publica COP 6,8 em frequência máxima.
    const cop = copFull(model, 26, 28);
    assert.ok(cop > 6 && cop < 7.6, `${model.name}: COP ${cop.toFixed(2)}`);
  }
});

test('COP sobe quando o inversor modula e nunca passa o teto do catálogo', () => {
  const m = MODELS[2];
  const full = copAt(m, 20, 29, 999);
  const half = copAt(m, 20, 29, capacityAt(m, 20, 29) / 2);
  const tiny = copAt(m, 20, 29, 0.1);
  assert.ok(half > full);
  assert.ok(tiny > half);
  const ceiling = full * (m.heat80.copMax / m.heat80.copMin);
  assert.ok(tiny <= ceiling + 1e-9, `teto ${ceiling} < ${tiny}`);
});

test('energia para aquecer 1 m³ em 1 °C', () => {
  close(KWH_PER_M3_K, 1.163, 0.001);
});

test('disjuntor sugerido cobre 1,25 × a corrente máxima', () => {
  for (const model of MODELS) {
    const a = suggestedBreakerA(model);
    assert.ok(a >= model.maxCurrentA * 1.25, `${model.name}: ${a} A`);
  }
  assert.equal(suggestedBreakerA(MODELS[0]), 10); // 7,3 A × 1,25 = 9,1 A
  assert.equal(suggestedBreakerA(MODELS[6]), 40); // 30 A × 1,25 = 37,5 A
});

test('poolLoad escala a perda pela área', () => {
  const p = { tWater: 28, tAir: 20, rh: 70, wind: 1 };
  const a = poolLoad(p, 32);
  const b = poolLoad(p, 64);
  close(b.total, a.total * 2, 1e-9);
});

const baseInput = {
  area: 32,
  volume: 44.8,
  tTarget: 28,
  tStart: 20,
  tAir: 17,
  rh: 78,
  altitude: 760,
  wind: 1.2,
  outdoor: true,
  cover: COVER_TYPES[1],
  coverHours: 14,
  solar: 3.9,
  useSolar: true,
  runHours: 10,
  heatUpHours: 48,
  tariff: 0.95,
  models: MODELS,
};

test('caso típico: piscina 8×4 em São Paulo no inverno', () => {
  const r = simulate(baseInput);
  // Perda instantânea com a piscina descoberta, ~700 W/m² nessa condição.
  assert.ok(r.maintenanceKw > 15 && r.maintenanceKw < 30, `manutenção ${r.maintenanceKw}`);
  // O dimensionamento é o maior dos dois deveres, nunca menor que cada um.
  assert.ok(r.requiredKw >= r.dutyDaily - 1e-9 && r.requiredKw >= r.dutyHeatUp - 1e-9);
  // A capa tem que derrubar bastante a perda.
  assert.ok(r.coveredMaintenanceKw < r.maintenanceKw * 0.35);
  // Aquecimento inicial: 44,8 m³ × 8 °C × 1,163.
  close(r.heatUpKwh, 44.8 * 8 * 1.163, 0.5);
  assert.ok(r.recommended, 'algum modelo deveria atender');
  assert.ok(r.recommended.capacity >= r.requiredKw);
  // O recomendado é o menor suficiente.
  const idx = r.rows.indexOf(r.recommended);
  for (let i = 0; i < idx; i += 1) assert.ok(!r.rows[i].sufficient);
});

test('sem capa a máquina necessária é maior', () => {
  const withCover = simulate(baseInput);
  const without = simulate({ ...baseInput, cover: COVER_TYPES[0], coverHours: 0 });
  assert.ok(without.netDailyKwh > withCover.netDailyKwh);
  assert.ok(without.requiredKw > withCover.requiredKw);
  // Sem capa, ou o modelo indicado é maior, ou nenhum da linha dá conta.
  const rank = (r) => {
    const i = r.rows.findIndex((x) => x.sufficient);
    return i === -1 ? Number.POSITIVE_INFINITY : i;
  };
  assert.ok(rank(without) > rank(withCover));
});

test('mais horas de funcionamento reduzem a carga instantânea e o custo', () => {
  const short = simulate({ ...baseInput, runHours: 6 });
  const long = simulate({ ...baseInput, runHours: 18 });
  const pick = (r) => r.rows.find((x) => x.model.id === 'ecopool-35');
  assert.ok(pick(long).loadKw < pick(short).loadKw);
  // Mesma energia no dia, entregue mais devagar: o inversor modula e gasta menos.
  assert.ok(pick(long).cop > pick(short).cop);
  assert.ok(pick(long).costDay < pick(short).costDay);
});

test('cenário inviável não produz custo — a piscina nunca chega à temperatura', () => {
  const r = simulate({ ...baseInput, runHours: 4 });
  const blocked = r.rows.filter((x) => !x.keepsUp);
  assert.ok(blocked.length > 0, 'com 4 h por dia algum modelo deveria ficar para trás');
  for (const row of blocked) {
    assert.ok(Number.isNaN(row.elecKwhDay), `${row.model.name} não deveria ter consumo`);
    assert.ok(Number.isNaN(row.costMonth));
    assert.ok(row.deliveredKwhDay > 0, 'ainda assim entrega alguma energia');
  }
});

test('ganho solar abate a energia diária', () => {
  const withSun = simulate(baseInput);
  const noSun = simulate({ ...baseInput, useSolar: false });
  assert.ok(noSun.netDailyKwh > withSun.netDailyKwh);
  assert.equal(withSun.dailyLossKwh, noSun.dailyLossKwh);
});

test('piscina grande e fria exige equipamento maior', () => {
  const small = simulate(baseInput);
  const big = simulate({ ...baseInput, area: 96, volume: 150, tTarget: 32, tAir: 12 });
  const idxSmall = small.rows.findIndex((r) => r.sufficient);
  const idxBig = big.rows.findIndex((r) => r.sufficient);
  assert.ok(idxBig === -1 || idxBig > idxSmall, `${idxSmall} → ${idxBig}`);
});

test('todas as linhas trazem custo e tempo de aquecimento finitos quando dão conta', () => {
  const r = simulate(baseInput);
  for (const row of r.rows.filter((x) => x.sufficient)) {
    assert.ok(Number.isFinite(row.heatUpHours) && row.heatUpHours > 0);
    assert.ok(row.costMonth > 0);
    assert.ok(row.cop > 2 && row.cop < 20, `${row.model.name}: COP ${row.cop}`);
  }
});
