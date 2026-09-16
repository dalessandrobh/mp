/** Ponto de entrada: monta a casca da página e liga o simulador. */

import { mount } from './ui.js';

const SHELL = `
  <header class="masthead">
    <div>
      <span class="kicker">Bomba de calor · trocador de piscina</span>
      <h1>Simulador de aquecimento de piscina</h1>
      <p>Informe a piscina, o clima e o uso. O cálculo devolve o modelo da linha
         ECOPOOL que dá conta do serviço, o tempo do primeiro aquecimento e
         quanto isso custa por mês.</p>
    </div>
  </header>
  <main class="layout">
    <div id="form-root"></div>
    <section class="results" id="results" aria-live="polite"></section>
  </main>
  <footer class="colophon">
    Dados de capacidade, consumo, COP e ficha técnica retirados do catálogo da
    linha ECOPOOL. O dimensionamento é uma estimativa de engenharia a partir
    desses dados — confirme com o fabricante antes de fechar um projeto.
  </footer>
`;

export function start(root) {
  root.innerHTML = SHELL;
  mount(document.getElementById('form-root'), document.getElementById('results'));
}

const app = document.getElementById('app');
if (app) start(app);
