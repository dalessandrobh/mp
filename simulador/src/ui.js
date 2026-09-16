/** Interface do simulador: monta o formulário, lê os campos e desenha o resultado. */

import { MODELS, COMMON_SPECS } from './data.js';
import { CITIES, WIND_PRESETS, COVER_TYPES } from './climate.js';
import {
  capacityAt,
  copAt,
  poolGeometry,
  simulate,
  suggestedBreakerA,
  num,
} from './engine.js';
import { duration, fmt, money } from './format.js';

const LOSS_SERIES = [
  { key: 'evaporation', label: 'Evaporação', slot: 1 },
  { key: 'radiation', label: 'Radiação', slot: 2 },
  { key: 'convection', label: 'Convecção', slot: 3 },
  { key: 'conduction', label: 'Condução', slot: 4 },
];

const CHART_TEMPS = [5, 10, 15, 20, 25, 30, 35];

const state = { focusModel: null };

// ------------------------------------------------------------------- markup

function options(list, selected) {
  return list
    .map(
      (o) =>
        `<option value="${o.id}"${o.id === selected ? ' selected' : ''}>${o.name}</option>`
    )
    .join('');
}

function field(id, label, input, hint) {
  return `<div class="field">
    <label for="${id}">${label}</label>
    ${input}
    ${hint ? `<p class="hint">${hint}</p>` : ''}
  </div>`;
}

function numberInput(id, value, { min, max, step = '0.1', suffix } = {}) {
  const attrs = [
    `id="${id}"`,
    `name="${id}"`,
    'type="number"',
    `value="${value}"`,
    `step="${step}"`,
    min !== undefined ? `min="${min}"` : '',
    max !== undefined ? `max="${max}"` : '',
    'inputmode="decimal"',
  ]
    .filter(Boolean)
    .join(' ');
  const control = `<input ${attrs}>`;
  return suffix
    ? `<div class="with-suffix"><input ${attrs}><span class="suffix">${suffix}</span></div>`
    : control;
}

export function formMarkup() {
  return `
  <form id="form" class="panel" novalidate>
    <fieldset>
      <legend>1 · A piscina</legend>
      ${field(
        'shape',
        'Formato',
        `<select id="shape" name="shape">
          <option value="rect" selected>Retangular</option>
          <option value="round">Redonda</option>
          <option value="oval">Oval</option>
          <option value="custom">Já sei a área e o volume</option>
        </select>`
      )}
      <div class="grid-2" data-shape-group="rect oval">
        ${field('length', 'Comprimento', numberInput('length', 8, { min: 1, suffix: 'm' }))}
        ${field('width', 'Largura', numberInput('width', 4, { min: 1, suffix: 'm' }))}
      </div>
      <div data-shape-group="round" hidden>
        ${field('diameter', 'Diâmetro', numberInput('diameter', 4.5, { min: 1, suffix: 'm' }))}
      </div>
      <div data-shape-group="rect round oval">
        ${field(
          'depth',
          'Profundidade média',
          numberInput('depth', 1.4, { min: 0.3, max: 4, suffix: 'm' }),
          'Média entre a parte rasa e a funda.'
        )}
      </div>
      <div class="grid-2" data-shape-group="custom" hidden>
        ${field('area', 'Espelho d’água', numberInput('area', 32, { min: 1, suffix: 'm²' }))}
        ${field('volume', 'Volume', numberInput('volume', 44.8, { min: 1, suffix: 'm³' }))}
      </div>
      <p class="readout" id="geometry-readout"></p>
    </fieldset>

    <fieldset>
      <legend>2 · Temperatura</legend>
      <div class="grid-2">
        ${field(
          'tTarget',
          'Água desejada',
          numberInput('tTarget', 29, { min: 18, max: 40, step: '0.5', suffix: '°C' })
        )}
        ${field(
          'tStart',
          'Água hoje',
          numberInput('tStart', 20, { min: 2, max: 40, step: '0.5', suffix: '°C' })
        )}
      </div>
      ${field(
        'heatUpHours',
        'Prazo para o primeiro aquecimento',
        numberInput('heatUpHours', 48, { min: 6, max: 240, step: '1', suffix: 'h' }),
        'Operação contínua, do jeito que se faz na partida da temporada.'
      )}
    </fieldset>

    <fieldset>
      <legend>3 · Clima e exposição</legend>
      ${field(
        'city',
        'Cidade de referência',
        `<select id="city" name="city">${options(CITIES, 'sp')}</select>`,
        'Preenche os campos abaixo com médias do período frio. Ajuste à vontade.'
      )}
      <div class="grid-2">
        ${field('tAir', 'Ar externo', numberInput('tAir', 17, { min: -10, max: 43, step: '0.5', suffix: '°C' }))}
        ${field('rh', 'Umidade relativa', numberInput('rh', 78, { min: 10, max: 100, step: '1', suffix: '%' }))}
      </div>
      <div class="grid-2">
        ${field('altitude', 'Altitude', numberInput('altitude', 760, { min: 0, max: 3000, step: '10', suffix: 'm' }))}
        ${field('solar', 'Irradiação diária', numberInput('solar', 3.9, { min: 0, max: 8, step: '0.1', suffix: 'kWh/m²' }))}
      </div>
      ${field(
        'wind',
        'Exposição ao vento',
        `<select id="wind" name="wind">${options(WIND_PRESETS, 'normal')}</select>`
      )}
      <label class="check" for="useSolar">
        <input type="checkbox" id="useSolar" name="useSolar" checked>
        <span>Descontar o ganho solar do consumo diário</span>
      </label>
    </fieldset>

    <fieldset>
      <legend>4 · Uso</legend>
      ${field(
        'cover',
        'Cobertura térmica',
        `<select id="cover" name="cover">${options(COVER_TYPES, 'bubble')}</select>`,
        'É o item que mais muda o resultado de uma piscina externa.'
      )}
      <div data-cover-group>
        ${field(
          'coverHours',
          'Horas por dia com a capa fechada',
          numberInput('coverHours', 16, { min: 0, max: 24, step: '1', suffix: 'h' })
        )}
      </div>
      ${field(
        'runHours',
        'Horas de funcionamento por dia',
        numberInput('runHours', 10, { min: 1, max: 24, step: '1', suffix: 'h' }),
        'Costuma acompanhar o tempo de filtragem — a bomba d’água precisa estar ligada.'
      )}
    </fieldset>

    <fieldset>
      <legend>5 · Energia</legend>
      ${field(
        'tariff',
        'Tarifa de energia',
        numberInput('tariff', 0.95, { min: 0.1, max: 5, step: '0.01', suffix: 'R$/kWh' }),
        'Com impostos, como aparece na conta.'
      )}
    </fieldset>
  </form>`;
}

// -------------------------------------------------------------------- leitura

function el(id) {
  return document.getElementById(id);
}

export function readInputs() {
  const shape = el('shape').value;
  const geo = poolGeometry({
    shape,
    length: num(el('length').value),
    width: num(el('width').value),
    diameter: num(el('diameter').value),
    depth: num(el('depth').value),
    area: num(el('area').value),
    volume: num(el('volume').value),
  });
  const windPreset = WIND_PRESETS.find((w) => w.id === el('wind').value) || WIND_PRESETS[2];
  const cover = COVER_TYPES.find((c) => c.id === el('cover').value) || COVER_TYPES[0];

  return {
    ...geo,
    tTarget: num(el('tTarget').value),
    tStart: num(el('tStart').value),
    heatUpHours: num(el('heatUpHours').value),
    tAir: num(el('tAir').value),
    rh: num(el('rh').value),
    altitude: num(el('altitude').value),
    solar: num(el('solar').value),
    useSolar: el('useSolar').checked,
    wind: windPreset.wind,
    outdoor: windPreset.outdoor,
    cover,
    coverHours: num(el('coverHours').value),
    runHours: num(el('runHours').value),
    tariff: num(el('tariff').value),
    models: MODELS,
  };
}

// ------------------------------------------------------------------- gráficos

function stackedBar(breakdown) {
  const total = LOSS_SERIES.reduce((s, x) => s + breakdown[x.key], 0) || 1;
  const segments = LOSS_SERIES.map((s) => {
    const kw = breakdown[s.key];
    const pct = (kw / total) * 100;
    return { ...s, kw, pct };
  }).filter((s) => s.pct > 0.05);

  const bar = segments
    .map(
      (s) =>
        `<span class="seg" style="flex:${s.pct};background:var(--series-${s.slot})" title="${s.label}: ${fmt(s.kw)} kW"></span>`
    )
    .join('');

  const legend = segments
    .map(
      (s) => `<li>
        <span class="swatch" style="background:var(--series-${s.slot})"></span>
        <span class="legend-label">${s.label}</span>
        <span class="legend-value">${fmt(s.pct, 0)}%</span>
        <span class="legend-sub">${fmt(s.kw)} kW</span>
      </li>`
    )
    .join('');

  return `<div class="bar">${bar}</div><ul class="legend">${legend}</ul>`;
}

/** Passos "redondos" (1, 2, 5 × 10ⁿ) para o eixo de kW. */
function niceTicks(maxY, target = 4) {
  const raw = maxY / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? mag * 10;
  const ticks = [];
  for (let v = 0; v <= maxY + 1e-9; v += step) ticks.push(v);
  return ticks;
}

/**
 * Mantém os dois rótulos de ponta dentro do desenho e afastados um do outro:
 * o de cima sobe, o de baixo desce, e nenhum invade o eixo.
 */
function labelY(capY, demandY, top = 34, bottom = 222) {
  const clamp = (v) => Math.min(Math.max(v, top), bottom);
  const capAbove = capY <= demandY;
  let cap = clamp(capY + (capAbove ? -10 : 16));
  let demand = clamp(demandY + (capAbove ? 16 : -10));
  if (Math.abs(cap - demand) < 14) {
    if (capAbove) demand = clamp(cap + 16);
    else cap = clamp(demand + 16);
  }
  return { cap: cap.toFixed(1), demand: demand.toFixed(1) };
}

/**
 * Capacidade do modelo × demanda da piscina, em função da temperatura do ar.
 * Uma escala só (kW), duas séries, rótulos diretos e leitura por hover.
 */
function capacityChart(model, input, result) {
  const W = 620;
  const H = 260;
  const pad = { t: 30, r: 18, b: 34, l: 48 };
  const points = CHART_TEMPS.map((t) => {
    const cap = capacityAt(model, t, result.tWaterOut);
    const demand = simulate({ ...input, tAir: t }).dutyDaily;
    return { t, cap, demand };
  });
  const maxY = Math.max(...points.flatMap((p) => [p.cap, p.demand])) * 1.15 || 1;
  const x = (t) =>
    pad.l + ((t - CHART_TEMPS[0]) / (CHART_TEMPS.at(-1) - CHART_TEMPS[0])) * (W - pad.l - pad.r);
  const y = (v) => H - pad.b - (v / maxY) * (H - pad.t - pad.b);

  const path = (key) => points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');

  const ticksY = niceTicks(maxY);
  const grid = ticksY
    .map(
      (v) =>
        `<line x1="${pad.l}" y1="${y(v).toFixed(1)}" x2="${W - pad.r}" y2="${y(v).toFixed(1)}" class="grid"></line>
         <text x="${pad.l - 8}" y="${(y(v) + 4).toFixed(1)}" class="tick" text-anchor="end">${fmt(v, 0)}</text>`
    )
    .join('');

  const ticksX = CHART_TEMPS.map(
    (t) => `<text x="${x(t).toFixed(1)}" y="${H - pad.b + 20}" class="tick" text-anchor="middle">${t}°</text>`
  ).join('');

  const hot = points
    .map(
      (p) => `<g class="hot" data-t="${p.t}" data-cap="${fmt(p.cap)}" data-demand="${fmt(p.demand)}">
        <rect x="${(x(p.t) - 22).toFixed(1)}" y="${pad.t}" width="44" height="${H - pad.t - pad.b}" fill="transparent"></rect>
        <line x1="${x(p.t).toFixed(1)}" y1="${pad.t}" x2="${x(p.t).toFixed(1)}" y2="${H - pad.b}" class="crosshair"></line>
        <circle cx="${x(p.t).toFixed(1)}" cy="${y(p.cap).toFixed(1)}" r="5" class="dot dot-cap"></circle>
        <circle cx="${x(p.t).toFixed(1)}" cy="${y(p.demand).toFixed(1)}" r="5" class="dot dot-demand"></circle>
      </g>`
    )
    .join('');

  const last = points.at(-1);
  return `
  <figure class="chart">
    <figcaption>
      <span class="chart-title">Capacidade do ${model.name} × demanda da piscina</span>
      <ul class="legend inline">
        <li><span class="swatch" style="background:var(--series-1)"></span><span class="legend-label">Capacidade do equipamento</span></li>
        <li><span class="swatch" style="background:var(--series-2)"></span><span class="legend-label">Demanda em ${fmt(result.runHours, 0)} h/dia</span></li>
      </ul>
    </figcaption>
    <div class="chart-box">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Capacidade e demanda em kW por temperatura do ar">
        ${grid}
        <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" class="axis"></line>
        ${ticksX}
        <path d="${path('cap')}" class="line line-cap"></path>
        <path d="${path('demand')}" class="line line-demand"></path>
        <text x="${(x(last.t) - 6).toFixed(1)}" y="${labelY(y(last.cap), y(last.demand)).cap}" class="point-label label-cap" text-anchor="end">${fmt(last.cap)} kW</text>
        <text x="${(x(last.t) - 6).toFixed(1)}" y="${labelY(y(last.cap), y(last.demand)).demand}" class="point-label label-demand" text-anchor="end">${fmt(last.demand)} kW</text>
        <text x="${pad.l - 8}" y="14" class="axis-title" text-anchor="end">kW</text>
        ${hot}
      </svg>
      <div class="tooltip" hidden></div>
    </div>
    <p class="chart-note">Temperatura do ar (°C) · o cruzamento das linhas marca o ponto em que o equipamento deixa de repor a perda dentro da janela de funcionamento.</p>
  </figure>`;
}

// -------------------------------------------------------------------- resultado

function statusOf(row, recommended) {
  if (!row.keepsUp) return { cls: 'critical', label: 'Não repõe a perda' };
  if (!row.sufficient) return { cls: 'warning', label: 'Abaixo do necessário' };
  if (recommended && row.model.id === recommended.model.id)
    return { cls: 'good', label: 'Indicado' };
  return { cls: 'neutral', label: 'Atende com folga' };
}

function verdict(result, input) {
  const rec = result.recommended;
  if (!rec) {
    return `<section class="verdict verdict-blocked">
      <p class="eyebrow">Nenhum modelo da linha atende</p>
      <h2>A demanda é de ${fmt(result.requiredKw)} kW</h2>
      <p class="verdict-text">
        O maior equipamento da linha entrega ${fmt(result.rows.at(-1).capacity)} kW nessas condições.
        Para fechar a conta: use capa térmica por mais horas, reduza a temperatura desejada,
        amplie as horas de funcionamento por dia, alongue o prazo do primeiro aquecimento
        ou associe duas máquinas em paralelo.
      </p>
    </section>`;
  }
  const row = result.rows.find((r) => r.model.id === rec.model.id);
  return `<section class="verdict">
    <p class="eyebrow">Indicado para ${fmt(result.area, 0)} m² · ${fmt(result.volume, 0)} m³</p>
    <h2>${rec.model.name}</h2>
    <p class="verdict-text">
      Entrega <strong>${fmt(row.capacity)} kW</strong> com ar a ${fmt(input.tAir, 0)} °C, contra
      <strong>${fmt(result.requiredKw)} kW</strong> necessários.
      Chega aos ${fmt(input.tTarget, 0)} °C em <strong>${duration(row.heatUpHours)}</strong> de operação contínua.
    </p>
  </section>`;
}

function tiles(result) {
  const row = result.selected;
  const items = [
    { label: 'Capacidade necessária', value: `${fmt(result.requiredKw)} kW`, sub: `manutenção + aquecimento` },
    { label: 'Energia no dia', value: `${fmt(result.netDailyKwh, 0)} kWh`, sub: `${fmt(result.dailyLossKwh, 0)} kWh de perda − ${fmt(result.solarKwh, 0)} kWh de sol` },
    {
      label: 'Consumo elétrico',
      value: row && row.keepsUp ? `${fmt(row.elecKwhDay, 0)} kWh/dia` : '—',
      sub: row && row.keepsUp ? `COP médio de ${fmt(row.cop)}` : 'depende de um equipamento que dê conta',
    },
    {
      label: 'Custo mensal',
      value: row && row.keepsUp ? money(row.costMonth) : '—',
      sub: row && row.keepsUp ? `${money(row.costDay)} por dia` : 'idem',
    },
  ];
  return `<div class="tiles">${items
    .map(
      (i) => `<div class="tile">
        <p class="tile-label">${i.label}</p>
        <p class="tile-value">${i.value}</p>
        <p class="tile-sub">${i.sub}</p>
      </div>`
    )
    .join('')}</div>`;
}

function lossSection(result, input) {
  const open = result.breakdown;
  const covered = result.coveredBreakdown;
  const hasCover = input.cover && input.cover.id !== 'none';
  const rows = LOSS_SERIES.map(
    (s) => `<tr>
      <th scope="row"><span class="swatch" style="background:var(--series-${s.slot})"></span>${s.label}</th>
      <td>${fmt(open[s.key])}</td>
      <td>${hasCover ? fmt(covered[s.key]) : '—'}</td>
    </tr>`
  ).join('');

  return `<section class="card">
    <h3>Para onde vai o calor</h3>
    <p class="card-sub">Piscina descoberta a ${fmt(input.tTarget, 0)} °C, ar a ${fmt(input.tAir, 0)} °C e ${fmt(input.rh, 0)}% de umidade: ${fmt(result.breakdown.perM2, 0)} W por m² de espelho d’água.</p>
    ${stackedBar(open)}
    <div class="table-wrap">
      <table class="data">
        <caption class="sr-only">Perda térmica por mecanismo, em kW</caption>
        <thead><tr><th scope="col">Mecanismo</th><th scope="col">Descoberta (kW)</th><th scope="col">Com a capa (kW)</th></tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr><th scope="row">Total</th><td>${fmt(open.total)}</td><td>${hasCover ? fmt(covered.total) : '—'}</td></tr></tfoot>
      </table>
    </div>
    ${
      hasCover
        ? `<p class="note">A capa corta ${fmt((1 - covered.total / open.total) * 100, 0)}% da perda enquanto está fechada — por isso ela entra no cálculo com ${fmt(result.coverHours, 0)} h por dia.</p>`
        : `<p class="note note-warn">Sem cobertura térmica, a evaporação responde por ${fmt((open.evaporation / open.total) * 100, 0)}% de tudo que a máquina precisa repor.</p>`
    }
  </section>`;
}

function comparison(result) {
  const rec = result.recommended;
  const rows = result.rows
    .map((row) => {
      const st = statusOf(row, rec);
      const isFocus = state.focusModel === row.model.id;
      return `<tr class="${isFocus ? 'is-focus' : ''}" data-model="${row.model.id}" tabindex="0">
        <th scope="row">${row.model.name}<span class="row-sub">${fmt(row.model.nominalKw, 0)} kW nominal</span></th>
        <td>${fmt(row.capacity)}</td>
        <td>${duration(row.heatUpHours)}</td>
        <td>${fmt(row.elecKwhDay, 0)}</td>
        <td>${money(row.costMonth)}</td>
        <td><span class="pill pill-${st.cls}">${st.label}</span></td>
      </tr>`;
    })
    .join('');

  return `<section class="card">
    <h3>A linha inteira nas suas condições</h3>
    <p class="card-sub">Clique numa linha para ver a ficha técnica do modelo.</p>
    <div class="table-wrap">
      <table class="data selectable">
        <thead><tr>
          <th scope="col">Modelo</th>
          <th scope="col">Capacidade (kW)</th>
          <th scope="col">1º aquecimento</th>
          <th scope="col">kWh/dia</th>
          <th scope="col">Custo/mês</th>
          <th scope="col">Situação</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </section>`;
}

function datasheet(row, input) {
  const m = row.model;
  const specs = [
    ['Capacidade nominal', `${m.nominalKw} kW · ${m.btuH.toLocaleString('pt-BR')} BTU/h`],
    ['Capacidade nas suas condições', `${fmt(row.capacity)} kW (ar ${fmt(input.tAir, 0)} °C, água saindo a ${fmt(input.tTarget + 1, 0)} °C)`],
    ['Modulação do inversor', `${fmt(row.minCapacity)} a ${fmt(row.capacity)} kW`],
    ['COP no ponto de trabalho', fmt(row.cop)],
    ['COP de catálogo (ar 26 °C / 80% UR)', `${fmt(m.heat80.copMax)} a ${fmt(m.heat80.copMin)}`],
    ['Potência máxima absorvida', `${fmt(m.maxInputKw)} kW`],
    ['Corrente máxima', `${fmt(m.maxCurrentA)} A`],
    ['Disjuntor sugerido', `${suggestedBreakerA(m)} A (1,25 × a corrente máxima)`],
    ['Alimentação', COMMON_SPECS.supply],
    ['Vazão de água nominal', `${fmt(m.waterFlowM3h)} m³/h`],
    ['Fluxo de ar', `${m.airFlowM3h.toLocaleString('pt-BR')} m³/h`],
    ['Fluido refrigerante', `${m.refrigerant} · ${m.chargeG} g`],
    ['Trocador de calor', COMMON_SPECS.heatExchanger],
    ['Degelo', COMMON_SPECS.defrost],
    ['Ruído a 1 m / 10 m', `${m.noise1m[0]}~${m.noise1m[1]} dB · ${m.noise10m[0]}~${m.noise10m[1]} dB`],
    ['Dimensões (L × P × A)', `${m.dimNetMm} mm`],
    ['Peso líquido', `${m.weightNetKg} kg`],
    ['Proteção', `${COMMON_SPECS.ingressProtection} · gabinete em ${COMMON_SPECS.casing}`],
  ];
  return `<section class="card">
    <h3>Ficha técnica — ${m.name}</h3>
    <dl class="specs">
      ${specs.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}
    </dl>
    <p class="note">A bomba de filtragem precisa entregar pelo menos ${fmt(m.waterFlowM3h)} m³/h com o trocador na linha. O disjuntor é uma indicação de partida — o dimensionamento final do circuito é do eletricista.</p>
  </section>`;
}

function warnings(result, input) {
  const items = [];
  const row = result.selected;
  if (row && !row.keepsUp) {
    items.push(
      `Em ${fmt(result.runHours, 0)} h por dia o ${row.model.name} não repõe a perda. Seriam necessárias ${duration(row.minHours)} de funcionamento.`
    );
  }
  if (row && row.cyclesShort) {
    items.push(
      `A carga do dia (${fmt(row.loadKw)} kW) fica abaixo da capacidade mínima do compressor (${fmt(row.minCapacity)} kW): o equipamento vai ligar e desligar em vez de modular.`
    );
  }
  if (input.tAir < 5) {
    items.push('Abaixo de 5 °C o degelo passa a atuar com frequência e a capacidade real cai mais do que a curva sugere.');
  }
  if (input.tTarget > 32) {
    items.push('Acima de 32 °C a água acelera muito a evaporação e o consumo cresce bem mais rápido que a temperatura.');
  }
  if ((!input.cover || input.cover.id === 'none') && input.outdoor) {
    items.push('Piscina externa sem capa térmica: a evaporação sozinha costuma dobrar a conta de energia.');
  }
  if (!items.length) return '';
  return `<section class="card card-warn">
    <h3>Atenção</h3>
    <ul class="warn-list">${items.map((i) => `<li>${i}</li>`).join('')}</ul>
  </section>`;
}

function assumptions() {
  return `<details class="card card-quiet">
    <summary>Como a conta é feita</summary>
    <ul class="assump">
      <li><strong>Evaporação</strong> — fluxo de massa (25 + 19·v) · (x<sub>água</sub> − x<sub>ar</sub>), com v em m/s e razões de umidade calculadas na pressão atmosférica da altitude informada.</li>
      <li><strong>Convecção</strong> — coeficiente h = 3,1 + 4,1·v sobre a diferença entre água e ar.</li>
      <li><strong>Radiação</strong> — corpo cinza (ε = 0,95) contra um céu 10 °C mais frio que o ar; em piscina coberta, contra o próprio ambiente.</li>
      <li><strong>Condução</strong> — 3% das perdas de superfície, pelas paredes e pelo fundo.</li>
      <li><strong>Capacidade</strong> — curva de aquecimento do catálogo interpolada na temperatura do ar, corrigida em 1% por °C de água acima ou abaixo dos 35 °C da curva.</li>
      <li><strong>COP</strong> — potência absorvida do catálogo com 1,2% de acréscimo por °C de água; o ganho de eficiência na modulação segue a própria faixa publicada (15,8 a 6,8).</li>
      <li><strong>Dimensionamento</strong> — o maior entre repor a energia do dia dentro da janela de funcionamento e cumprir o primeiro aquecimento no prazo pedido.</li>
    </ul>
    <p class="note">É uma estimativa de engenharia com dados de catálogo. Vento real, sombreamento, chuva, reposição de água e uso da piscina mudam o resultado — para um projeto executivo, confirme com o fabricante.</p>
  </details>`;
}

export function resultsMarkup(result, input) {
  const focus =
    result.rows.find((r) => r.model.id === state.focusModel) || result.selected;
  return `
    ${verdict(result, input)}
    ${tiles(result)}
    ${warnings(result, input)}
    ${focus ? capacityChart(focus.model, input, result) : ''}
    ${lossSection(result, input)}
    ${comparison(result)}
    ${focus ? datasheet(focus, input) : ''}
    ${assumptions()}
  `;
}

// -------------------------------------------------------------------- wiring

function syncShapeGroups() {
  const shape = el('shape').value;
  document.querySelectorAll('[data-shape-group]').forEach((node) => {
    node.hidden = !node.dataset.shapeGroup.split(' ').includes(shape);
  });
  const coverGroup = document.querySelector('[data-cover-group]');
  if (coverGroup) coverGroup.hidden = el('cover').value === 'none';
}

function applyCity() {
  const city = CITIES.find((c) => c.id === el('city').value);
  if (!city || city.id === 'custom') return;
  el('tAir').value = city.tAir;
  el('rh').value = city.rh;
  el('solar').value = city.solar;
  el('altitude').value = city.alt;
}

function attachChartTooltip(root) {
  const box = root.querySelector('.chart-box');
  if (!box) return;
  const tip = box.querySelector('.tooltip');
  box.querySelectorAll('.hot').forEach((g) => {
    const show = () => {
      g.classList.add('is-on');
      tip.innerHTML = `<strong>${g.dataset.t} °C</strong>
        <span><span class="swatch" style="background:var(--series-1)"></span>Capacidade ${g.dataset.cap} kW</span>
        <span><span class="swatch" style="background:var(--series-2)"></span>Demanda ${g.dataset.demand} kW</span>`;
      tip.hidden = false;
      const rect = g.getBoundingClientRect();
      const host = box.getBoundingClientRect();
      const left = rect.left - host.left + rect.width / 2;
      tip.style.left = `${Math.min(Math.max(left, 70), host.width - 70)}px`;
    };
    const hide = () => {
      g.classList.remove('is-on');
      tip.hidden = true;
    };
    g.addEventListener('mouseenter', show);
    g.addEventListener('mouseleave', hide);
    g.addEventListener('focus', show);
    g.addEventListener('blur', hide);
  });
}

export function render(resultsRoot) {
  syncShapeGroups();
  const input = readInputs();
  const result = simulate(input);

  const geo = el('geometry-readout');
  if (geo) {
    geo.textContent = `${fmt(result.area, 1)} m² de espelho d’água · ${fmt(result.volume, 1)} m³ de água`;
  }

  resultsRoot.innerHTML = resultsMarkup(result, input);
  attachChartTooltip(resultsRoot);

  resultsRoot.querySelectorAll('tr[data-model]').forEach((tr) => {
    const pick = () => {
      state.focusModel = tr.dataset.model;
      render(resultsRoot);
    };
    tr.addEventListener('click', pick);
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pick();
      }
    });
  });
}

export function mount(formRoot, resultsRoot) {
  formRoot.innerHTML = formMarkup();
  const form = el('form');
  form.addEventListener('input', (e) => {
    if (e.target.id === 'city') applyCity();
    if (['tAir', 'rh', 'solar', 'altitude'].includes(e.target.id)) el('city').value = 'custom';
    render(resultsRoot);
  });
  form.addEventListener('change', () => render(resultsRoot));
  form.addEventListener('submit', (e) => e.preventDefault());
  applyCity();
  render(resultsRoot);
}
