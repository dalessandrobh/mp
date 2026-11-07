# Plano para R$ 10.000/mês de comissão

Documento de trabalho. Números medidos no banco de produção em 2026-11-02.
Revisar a cada fim de fase.

---

## 1. A conta, antes de qualquer coisa

Comissão do mês = (nº de vendas) × (comissão média por venda).

A seleção de produtos controla o segundo fator. A distribuição controla o primeiro.
Os dois são multiplicativos, e é por isso que mexer só em um não chega ao alvo.

| Comissão média/venda | Vendas/mês para R$ 10k | Vendas/dia | Cliques/dia (CVR 2%) | Alcance/dia (click rate 1,5%) |
|---|---|---|---|---|
| R$ 3,03 (catálogo hoje) | 3.300 | 110 | 5.500 | 367.000 |
| R$ 10 | 1.000 | 33 | 1.650 | 110.000 |
| R$ 20 | 500 | 17 | 833 | 56.000 |
| R$ 35 | 286 | 10 | 477 | 32.000 |

Leitura: subir a comissão média de R$ 3 para R$ 30 **divide por dez** o tráfego necessário.
É a alavanca mais barata que existe no sistema, e é 100% automatizável.
Mesmo no melhor cenário sobra a necessidade de ~30 mil de alcance por dia (~1 milhão/mês).
Esse é o trabalho de verdade.

CVR de 2% e click rate de 1,5% são premissas de partida da literatura de afiliados BR;
a Fase 0 existe para substituí-las por medição nossa.

---

## 2. Diagnóstico: o catálogo de hoje não sustenta o objetivo

1.061 produtos com preço e comissão medidos:

| Faixa de comissão por venda | Produtos |
|---|---|
| < R$ 5 | 910 (86%) |
| R$ 5 – 10 | 106 |
| R$ 10 – 15 | 22 |
| **≥ R$ 15** | **23** |
| **≥ R$ 20** | **13** |

- Preço mediano: **R$ 22,99**. Taxa média de comissão: 7,81%.
- Comissão média por venda: **R$ 3,03**.
- Produtos com taxa ≥ 15%: 109 — mas apenas **5** com taxa ≥ 15% *e* preço R$ 80–300.
- Receita real acumulada até hoje: **R$ 8,22** em 4 conversões (20/10). Linha de base ≈ zero.

### A causa

A descoberta ordena por unidades vendidas (`sortType 2`). Coisa barata vende mais unidade,
então o top 40 de cada categoria é povoado por itens de R$ 20. O sistema está otimizando
popularidade quando o objetivo é receita. **A cauda de comissão alta existe e nós não a estamos
olhando.**

Prova disso no próprio catálogo, os poucos que escaparam:

| Produto | Preço | Taxa | Comissão/venda | Vendas |
|---|---|---|---|---|
| Sérum retinol (Beleza) | R$ 135,99 | 25% | **R$ 34,00** | 14.882 |
| Bicicleta ergométrica | R$ 449,99 | 9% | **R$ 40,50** | 5.128 |
| Massageador de pescoço | R$ 102,99 | 28% | **R$ 28,84** | 531 |
| Jogo de panelas 10 pç | R$ 199,99 | 11% | **R$ 22,00** | 9.146 |

O ponto doce é **preço R$ 100–250 × taxa ≥ 15%**: comissão de R$ 20–50 por venda com demanda
provada. Beleza (taxa média 10,5%) e Saúde e Bem-estar (9,7%) são as categorias mais ricas;
Papelaria (7,8%, melhor caso R$ 3,29) não deveria consumir slot nenhum.

### O Opportunity Score atual não serve ao objetivo

`opp_v2` é média ponderada de componentes normalizados, com `COMMISSION_SATURATION_BRL = 30`
e `DEMAND_SATURATION_SALES = 5000`. Consequência: um produto de R$ 3 de comissão com 50 mil
vendas empata ou ganha de um de R$ 34 com 14 mil vendas. Como *score de qualidade* está
correto; como *critério de quem ocupa o slot de hoje* está errado, porque não é uma estimativa
de receita.

---

## 3. O motor de seleção estatístico

Trocar "score de 0 a 100" por **valor esperado de comissão por slot**, com incerteza explícita.

### 3.1 Função objetivo

Para o produto *k*:

```
EV_k = alcance × ctr_k × p_k × r_k
```

- `r_k` = preço × taxa — **conhecido exatamente** pela API. Sem incerteza.
- `p_k` = P(compra | clique) — desconhecido, aprendido.
- `ctr_k` = P(clique | alcance) — desconhecido, aprendido.
- alcance é do canal, não do produto: sai do ranking (constante multiplicativa).

Ranking por `ctr_k · p_k · r_k`. É a mesma matemática de um leilão de anúncio (eCPM), aplicada
a um recurso escasso que não é dinheiro, é slot de publicação.

### 3.2 Bayes empírico para as taxas (o pedaço que evita a maior armadilha)

Um produto com 1 venda em 3 cliques não converte a 33%. Modelo Beta-Binomial com prior tirado
da própria categoria (*empirical Bayes*, pooling parcial):

```
p_k ~ Beta(α₀ + vendas_k , β₀ + cliques_k − vendas_k)
p̂_k = (α₀ + vendas_k) / (α₀ + β₀ + cliques_k)
```

`α₀, β₀` por método dos momentos sobre a média `m` e a variância `v` agregadas da categoria:

```
α₀ + β₀ = m(1−m)/v − 1          α₀ = m(α₀+β₀)
```

Com força de prior limitada (equivalente a no máximo ~200 cliques), para que a evidência
própria do produto domine quando ela chegar. Hierarquia de pooling, do mais forte ao mais
fraco: **global → categoria → faixa de preço → produto**. Cada nível só assume o comando
quando tem amostra para isso.

### 3.3 Decidir com o limite inferior, explorar com o superior

- **Promover/manter**: percentil 10 da posterior (limite inferior de Beta / Wilson). Conservador —
  só entra no portfólio quem é bom até no pessimismo.
- **Testar**: percentil 90 (otimismo diante da incerteza, UCB). Produto sem dado nenhum tem
  limite superior alto *por não ter sido medido*, e é exatamente assim que ele ganha a primeira
  chance.

Isso já é a regra do projeto ("só dado SETTLED autoriza cortar") escrita em estatística.

### 3.4 Thompson sampling para alocar os slots

São ~3–10 publicações/dia e centenas de candidatos: é um *multi-armed bandit* com orçamento de
slots. Todo dia, para cada candidato:

1. sorteia `p̃_k ~ Beta(α_k, β_k)` e `ctr̃_k` análogo;
2. calcula `ṽ_k = ctr̃_k · p̃_k · r_k`;
3. ocupa os slots com os maiores `ṽ_k`, respeitando a cota por categoria.

Thompson sampling tem *regret* O(√(KT log T)) — perto do ótimo — e **substitui o
`EXPLOITATION_PERCENTAGE = 70 / EXPLORATION_PERCENTAGE = 30` fixo** por uma proporção que se
ajusta sozinha: muita exploração enquanto não se sabe nada, convergência conforme a evidência
chega. Um parâmetro a menos para ninguém calibrar à mão.

### 3.5 Teste A/B por produto é inviável aqui — e o sistema não deve fingir que não é

Para distinguir CVR de 2% de CVR de 3% com α=0,05 e poder 80%:

```
n = (1,96 + 0,84)² · [0,02·0,98 + 0,03·0,97] / (0,01)² ≈ 3.800 cliques por braço
```

Com algumas centenas de cliques/dia em toda a operação, um único teste conclusivo levaria
semanas e consumiria todo o tráfego. `MIN_CLICKS_FOR_DECISION = 50` serve como portão de
sanidade, **nunca** como significância — 50 cliques não distinguem 2% de 6%.

Daí a arquitetura acima: nada de p-valor por produto. Prior forte (comissão × momento × nota),
pooling parcial por categoria e faixa de preço, bandit para deixar a evidência se acumular sem
desperdiçar slot. É a resposta honesta para amostra pequena.

### 3.6 Momento, a partir da nossa série de snapshots

Medido hoje: `sales` da Shopee **não é acumulado** — sobe e desce centenas de unidades no mesmo
dia (27 subidas, 20 quedas em 241 pares consecutivos). É janela móvel. Então a derivada do
valor da janela é a *aceleração* das vendas: janela subindo = produto entrando em tendência.
É o sinal mais valioso que temos e nenhum concorrente que só lê a API tem.

- Inclinação por **Theil–Sen** (mediana das inclinações par a par) sobre os últimos 7–14 pontos:
  robusto a ruído e a reset de janela, que uma regressão simples não é.
- **Momento relativo** = inclinação / nível, adimensional e comparável entre produtos.
- Série irregular: `_unchanged` não grava snapshot sem mudança, então o Δ usa sempre
  `captured_at`, nunca "1 dia".

### 3.7 Censura à direita (viés de sobrevivência)

Produto que cai do top 40 da categoria para de gerar snapshot. Isso **não** é dado faltando —
é informação negativa. Regra: ausente do feed por *d* dias ⇒ penalidade no momento e refetch
nominal. (A confirmar: se a API aceita busca por `itemId`; se não, cai para busca por título
exato.)

### 3.8 Diversificação

Categorias compartilham choque de demanda. A cota por categoria (`MAX_CATEGORY_SHARE_PCT = 40`,
já em produção) cobre parte. Falta: teto por loja e mínimo de categorias distintas no
portfólio, para que uma sazonalidade ruim não zere o mês.

---

## 4. O gargalo real é distribuição

Seleção perfeita entrega ~R$ 0,70 de comissão por clique (R$ 35 × 2%) contra R$ 0,06 de hoje.
Ainda assim R$ 10k/mês pede ~15 mil cliques/mês. Instagram orgânico partindo de zero não
produz isso em 30 dias — nenhum ajuste de algoritmo muda esse fato.

Canais, por automação e por capacidade de composição:

| Canal | Automatizável | Alcance acumula? | Observação |
|---|---|---|---|
| **Pinterest** (API) | **alta** — criação de pin por API | **sim** — é buscador, pin de 6 meses atrás ainda traz clique | melhor relação esforço/retorno; não exige audiência prévia |
| Página catálogo (nossa) | total | sim (é o hub) | mede clique, que hoje não medimos |
| Instagram feed/reels | média — Graph API publica para conta Business | pouco | exige audiência; cold start lento |
| WhatsApp/Telegram (grupos próprios ou parceiros) | média | não, mas converte muito | alcance emprestado: o atalho mais rápido |
| Meta Ads | alta | não (para quando o pagamento para) | permitido pelos Termos 2.3(b); ver §7 |
| Google/Bing Ads | — | — | **proibido** (Termos 4.3(i)) |

**Pinterest é a escolha óbvia para "o mais automatizado possível"**: 1.061 produtos × vários pins
cada, criados por API, indexados por busca, compondo tráfego sem depender de seguidores.

Roteamento obrigatório: pin → **nossa página de catálogo com `noindex`** → link de afiliado.
Nunca pin apontando direto para o link de afiliado (Termos 4.3(k): URL com ID de afiliado não
pode ser indexada). O desvio pela nossa página é o que torna isso compatível *e* o que nos dá
a contagem de cliques que o bandit precisa.

---

## 5. Fases

Cada fase entrega algo que funciona sozinho. Nenhuma depende de a seguinte existir.

### Fase 0 — Fundação de medição e oferta (esta semana) — **feita em 02/11/2026**

Itens 1 a 4 implantados. O que mudou de fato: `/go/{sub_id}` conta clique, `/l` é a vitrine
`noindex`, a varredura por preço decrescente alcança a cauda de comissão alta, a
qualificação tem piso de comissão em dinheiro, e `ev_v1` passou a decidir quem ocupa vaga e
slot. Falta medir o resultado em produção.

Sem isso nada do resto é mensurável, e a janela de 11.11 (dia 11, em 9 dias) e Black Friday
(27/11) passa em branco.

1. **Varredura de comissão alta.** Descoberta passa a fazer dois sweeps por categoria: o atual
   por vendas e um novo em profundidade (até os 500 do teto) filtrando localmente por
   `preço × taxa`. 25 categorias × 500 = 12.500 produtos/dia, ~625 chamadas — cabe no rate
   limit. Meta: sair de 23 para 200+ produtos com comissão ≥ R$ 15.
2. **Página catálogo** com `noindex`, um redirect `/go/{creative_id}` que **conta o clique** e
   manda para o link de afiliado. Fecha o funil: hoje medimos venda sem medir clique, e sem
   clique não há CVR nem bandit.
3. **Ranking por EV v1** — `ctr · p · r` com prior puro (ainda sem dado próprio): comissão por
   venda × momento relativo × qualidade. Já reordena o portfólio hoje.
4. **Qualificação com piso de comissão por venda** (ex.: ≥ R$ 8), não só taxa ≥ 3%. Produto de
   R$ 1,50 de comissão não deveria chegar a candidato.

Receita esperada: R$ 300 – 1.200 (empurrada pela sazonalidade, não pelo nosso alcance).

### Fase 1 — Pinterest automatizado (novembro) — **item 5 feito em 03/11/2026**

5. ~~Adapter Pinterest + workflow n8n~~ **feito**: `adapters/social/pinterest/`, workflow 04
   em ramo paralelo, canal de atribuição `pin` próprio, guarda de marca que barra o suspeito.
   **Bloqueado em aprovação externa**: no Trial access do Pinterest o pin é visível só para
   o dono da conta, então o alcance real depende do Standard access (vídeo do fluxo OAuth +
   revisão, sem prazo divulgado). Enquanto isso, `MOCK_SOCIAL=true` e autonomia 3 deixam o
   fluxo inerte.
   **Revisado em 07/11/2026:** a regra 4.3 das Diretrizes de Desenvolvedor do Pinterest
   exige que a pessoa escolha cada pin publicado, então o MP deixou de publicar sozinho:
   propõe numa fila de aprovação (painel, menu Publicação) e o workflow 04b publica só o
   aprovado. A automação que sobra é a de escolher candidatos e gerar legenda e link.
6. 10–25 pins/dia, com teto para não acionar antispam. Em 30 dias: 300–750 pins compondo.
7. Pacote de 11.11 e Black Friday: lista por categoria com maior aceleração nos 3 dias
   anteriores ao evento.

Receita esperada: R$ 800 – 2.500 em dezembro (o pin de novembro só rende em dezembro).

### Fase 2 — Aprendizado fechando o ciclo (dezembro)

8. Beta-Binomial com pooling por categoria, alimentado por clique real da Fase 0.
9. Thompson sampling substituindo o 70/30 fixo.
10. Instagram Graph API publicando sozinho (conta Business), pacote diário deixa de ser manual.
11. Atribuição por `itemId` como fallback quando o `sub_id` não volta.

Receita esperada: R$ 2.000 – 5.000.

### Fase 3 — Escala (janeiro em diante)

12. Sazonalidade multiplicativa por categoria, aprendida da nossa própria série.
13. Teto por loja, mínimo de categorias distintas.
14. **Ponto de decisão sobre tráfego pago** (ver §7).

Receita esperada: R$ 5.000 – 10.000 por volta do mês 5–6 no caminho só-orgânico.

---

## 6. Automático vs. humano

**Roda sozinho ao fim da Fase 2:** descoberta e varredura de comissão alta · qualificação ·
score de oportunidade e EV · momento e aceleração · escolha de quem ocupa cada slot · geração
de legenda, imagem e link rastreado · publicação no Pinterest e no Instagram · contagem de
clique · sync de vendas e atribuição por post · performance score · corte e substituição de
produto · relatório diário no WhatsApp às 21h.

**Continua humano, por decisão de projeto:** ativar campanha paga (nunca por endpoint) · subir
nível de autonomia · aprovar mudança de parâmetro de risco · responder comentário e DM ·
fornecer `SHOPEE_VALIDATION_IDS`.

---

## 7. Riscos e a decisão que não é minha

**O alvo e o prazo.** R$ 10k/mês é alcançável só com orgânico, mas o caminho é de 5 a 6 meses,
porque depende de alcance composto. Se a restrição for *R$ 10k dentro de ~60 dias*, orgânico não
chega — e a alavanca que os Termos permitem é Meta Ads (2.3(b), só pela conta registrada).
Ordem de grandeza: ROAS 2–3× sobre comissão pede R$ 3–5k/mês de mídia para R$ 10k de comissão,
com risco real de queimar caixa enquanto a curva de aprendizado roda. Google e Bing Ads seguem
proibidos (4.3(i)), sem exceção.

A arquitetura das Fases 0–2 serve aos dois caminhos: o motor de seleção, a medição de clique e
o bandit são os mesmos. Ligar pago depois não joga nada fora.

**Riscos técnicos:** teto de 500 itens por lista limita o quanto a cauda é visível · `sales`
é janela móvel de semântica não documentada (nossa leitura é medida, não oficial) · censura do
top 40 enviesa a série · Pinterest pode marcar volume alto como spam · `validatedReport` sem
`validationId` mantém a comissão liquidada fora do sistema.

**Compliance, invariante:** sem marca/nome/logo Shopee no conteúdo (2.3(a)) · URL com ID de
afiliado nunca indexada, daí o `noindex` (4.3(k)) · aviso de afiliado em todo post · campanha
sempre criada PAUSADA · antes de qualquer mídia paga, confirmação por escrito do suporte Shopee.

---

## 8. Próximo passo

Fase 0, itens 1 a 4, nesta ordem. O item 2 (contagem de clique) é o que destrava todo o
aprendizado posterior e por isso não deve ficar para depois.
