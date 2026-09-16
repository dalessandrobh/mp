# Simulador de bomba de calor para piscina

Aplicação estática (HTML + ES modules, sem build e sem dependências) que
dimensiona uma bomba de calor da linha **ECOPOOL** para aquecer uma piscina:
diz qual modelo dá conta, em quanto tempo a piscina chega à temperatura pedida
e quanto isso custa por mês.

```
simulador/
├── index.html        página completa (abrir com um servidor estático)
├── artifact.html     mesma página, sem o esqueleto <html>, para publicação
├── styles.css        tokens de cor (claro/escuro), layout e componentes
├── src/
│   ├── data.js       ficha técnica da linha ECOPOOL — só dados de catálogo
│   ├── climate.js    clima de referência por cidade, vento e coberturas
│   ├── engine.js     psicrometria, perdas térmicas e seleção do modelo
│   ├── format.js     formatação pt-BR
│   ├── ui.js         formulário, gráficos e tabelas
│   └── boot.js       ponto de entrada
└── test/             testes do motor (node --test)
```

## Rodando

Os módulos ES exigem HTTP — abrir o arquivo direto do disco não funciona.

```bash
cd simulador
python3 -m http.server 8000
# http://localhost:8000/index.html
```

## Testes

```bash
cd simulador
node --test "test/*.test.mjs"
```

Os testes cobrem psicrometria contra valores tabelados, a reprodução exata da
curva do catálogo, a faixa de COP publicada, a ordem de grandeza das perdas, o
efeito da capa térmica e o comportamento do dimensionamento.

## O modelo de cálculo

### Perdas da piscina

Calculadas por m² de espelho d'água e decompostas por mecanismo.

| Mecanismo | Correlação |
|---|---|
| Evaporação | `ṁ = (25 + 19·v) · (x_água − x_ar)` em kg/(m²·h), convertida por `h_fg = 2430 kJ/kg`. Correlação de camada limite sobre lâmina d'água (VDI 2089 / Bernier). |
| Convecção | `h = 3,1 + 4,1·v` [W/(m²·K)] sobre a diferença água–ar. |
| Radiação | Corpo cinza, `ε = 0,95`, contra um céu 10 °C abaixo do ar (piscina externa) ou contra o próprio ambiente (piscina coberta). |
| Condução | 3% das perdas de superfície, por paredes e fundo. |

`v` é a velocidade do ar na lâmina d'água, vinda do preset de exposição. As
razões de umidade saem de Magnus-Tetens para a pressão de vapor e da pressão
atmosférica corrigida pela altitude — daí a diferença real entre Santos e
Brasília.

A cobertura térmica entra como fator por mecanismo (capa de bolha: 5% da
evaporação, 30% da convecção, 35% da radiação), ponderada pelas horas do dia em
que fica fechada.

O ganho solar abate o consumo — nunca o dimensionamento — considerando 11 h de
sol, absortividade de 0,85 e atenuação quando a capa está fechada.

### Desempenho do equipamento

Tudo sai do catálogo, sem constante inventada:

- **Capacidade** — a curva de aquecimento (ar de −10 °C a 43 °C, água entrando a
  33 °C e saindo a 35 °C) interpolada linearmente, corrigida em **1% por °C** de
  água acima ou abaixo dos 35 °C da curva. Esse coeficiente é o que concilia a
  própria curva com a tabela de 26 °C/80% UR do catálogo (7,05 kW contra 7,6 kW
  no ECOPOOL 7).
- **Potência absorvida** — a de frequência máxima do catálogo, com 1,2% de
  acréscimo por °C de água acima dos 28 °C da condição nominal.
- **COP** — capacidade dividida pela potência absorvida. Na condição nominal isso
  devolve os 6,8 publicados.
- **Modulação** — o ganho entre frequência mínima e máxima é a razão publicada
  (15,8 / 6,8 ≈ 2,3), aplicado linearmente entre a capacidade mínima e a máxima.
  Abaixo da capacidade mínima o compressor cicla, com 8% de penalidade.

### Dimensionamento

O modelo indicado é o **menor** que atende aos dois deveres:

1. **Regime** — repor a energia líquida do dia dentro da janela de funcionamento
   informada (que costuma ser a da filtragem).
2. **Primeiro aquecimento** — levar a água da temperatura atual à desejada no
   prazo pedido, em operação contínua, já descontadas as perdas do caminho.

`requerido = max(energia_do_dia / horas_por_dia, energia_de_aquecimento / prazo + perda_média)`

Quando nenhum modelo atende, a tela diz isso em vez de indicar o maior da linha.
E quando um modelo não repõe a perda, consumo e custo aparecem como `—`: a
piscina nunca chega à temperatura pedida, então esse custo não existe.

## Limites conhecidos

- Os dados climáticos por cidade são **médias aproximadas do período frio**, para
  dar um ponto de partida. Todos os campos continuam editáveis.
- Degelo, chuva, reposição de água e o calor levado por quem sai da piscina não
  entram no balanço. Abaixo de 5 °C a capacidade real cai mais do que a curva
  sugere — a tela avisa.
- O COP de carga parcial segue a faixa do fabricante, medida em condição
  favorável. Em campo é comum ficar abaixo disso.
- É uma estimativa de engenharia a partir de dados de catálogo, não substitui o
  projeto do fabricante.
