/**
 * Valores climáticos de REFERÊNCIA para a estação fria (outono/inverno).
 *
 * São médias aproximadas, pensadas só para dar um ponto de partida ao
 * dimensionamento — não substituem dados normais de uma estação meteorológica.
 * Todo campo preenchido por aqui continua editável na tela.
 *
 *  tAir  — temperatura média do ar no período frio [°C]
 *  rh    — umidade relativa média [%]
 *  solar — irradiação global horizontal média diária no período frio [kWh/m²/dia]
 *  alt   — altitude aproximada [m]
 */
export const CITIES = [
  { id: 'custom', name: 'Definir manualmente', tAir: 18, rh: 70, solar: 4.2, alt: 0 },
  { id: 'belem', name: 'Belém — PA', tAir: 26, rh: 85, solar: 4.4, alt: 10 },
  { id: 'bh', name: 'Belo Horizonte — MG', tAir: 19, rh: 65, solar: 4.7, alt: 850 },
  { id: 'brasilia', name: 'Brasília — DF', tAir: 19, rh: 55, solar: 5.2, alt: 1100 },
  { id: 'campinas', name: 'Campinas — SP', tAir: 18, rh: 72, solar: 4.4, alt: 690 },
  { id: 'campogrande', name: 'Campo Grande — MS', tAir: 20, rh: 70, solar: 4.6, alt: 590 },
  { id: 'caxias', name: 'Caxias do Sul — RS', tAir: 12, rh: 80, solar: 3.4, alt: 800 },
  { id: 'cuiaba', name: 'Cuiabá — MT', tAir: 23, rh: 65, solar: 4.8, alt: 180 },
  { id: 'curitiba', name: 'Curitiba — PR', tAir: 13, rh: 80, solar: 3.6, alt: 930 },
  { id: 'floripa', name: 'Florianópolis — SC', tAir: 16, rh: 82, solar: 3.7, alt: 10 },
  { id: 'fortaleza', name: 'Fortaleza — CE', tAir: 26, rh: 75, solar: 5.4, alt: 20 },
  { id: 'goiania', name: 'Goiânia — GO', tAir: 21, rh: 55, solar: 5.1, alt: 750 },
  { id: 'joinville', name: 'Joinville — SC', tAir: 16, rh: 82, solar: 3.6, alt: 20 },
  { id: 'londrina', name: 'Londrina — PR', tAir: 17, rh: 72, solar: 4.1, alt: 570 },
  { id: 'manaus', name: 'Manaus — AM', tAir: 26, rh: 85, solar: 4.4, alt: 60 },
  { id: 'poa', name: 'Porto Alegre — RS', tAir: 15, rh: 78, solar: 3.3, alt: 10 },
  { id: 'recife', name: 'Recife — PE', tAir: 24, rh: 80, solar: 4.8, alt: 10 },
  { id: 'ribeirao', name: 'Ribeirão Preto — SP', tAir: 19, rh: 62, solar: 4.7, alt: 550 },
  { id: 'rio', name: 'Rio de Janeiro — RJ', tAir: 22, rh: 77, solar: 4.3, alt: 10 },
  { id: 'salvador', name: 'Salvador — BA', tAir: 24, rh: 80, solar: 4.6, alt: 10 },
  { id: 'sp', name: 'São Paulo — SP', tAir: 17, rh: 78, solar: 3.9, alt: 760 },
  { id: 'uberlandia', name: 'Uberlândia — MG', tAir: 19, rh: 60, solar: 4.9, alt: 860 },
  { id: 'vitoria', name: 'Vitória — ES', tAir: 21, rh: 78, solar: 4.4, alt: 10 },
];

/** Exposição ao vento na lâmina d'água → velocidade do ar [m/s]. */
export const WIND_PRESETS = [
  { id: 'indoor', name: 'Piscina coberta / ambiente fechado', wind: 0.15, outdoor: false },
  { id: 'abrigada', name: 'Abrigada (muros altos, recuada)', wind: 0.6, outdoor: true },
  { id: 'normal', name: 'Pouco exposta (quintal urbano)', wind: 1.2, outdoor: true },
  { id: 'exposta', name: 'Exposta (terreno aberto)', wind: 2.2, outdoor: true },
  { id: 'muito', name: 'Muito exposta (litoral, campo, alto)', wind: 3.5, outdoor: true },
];

/** Cobertura térmica: fator de redução por mecanismo de perda. */
export const COVER_TYPES = [
  { id: 'none', name: 'Sem cobertura', evap: 1, conv: 1, rad: 1, solar: 1 },
  { id: 'bubble', name: 'Capa térmica (bolha / térmica flutuante)', evap: 0.05, conv: 0.3, rad: 0.35, solar: 0.6 },
  { id: 'rigid', name: 'Cobertura rígida / deck fechado', evap: 0.02, conv: 0.15, rad: 0.2, solar: 0.1 },
];
