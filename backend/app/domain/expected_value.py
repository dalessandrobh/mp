"""Valor esperado de comissão por clique (ev_v1). Função pura, sem banco e sem LLM.

Por que isto existe ao lado do Opportunity Score, e não no lugar dele: `opp_v2` é média
ponderada de componentes normalizados — responde "este produto é bom?". A pergunta que a
meta de comissão faz é outra: "quanto de comissão este produto rende se eu gastar com ele
o recurso escasso que eu tenho?". Recurso escasso aqui não é dinheiro, é SLOT de
publicação: são 3 a 10 por dia para centenas de candidatos.

    EV por clique = r × p

* `r` = comissão em dinheiro por venda = preço × taxa. **Conhecido exatamente** pela API,
  sem incerteza nenhuma.
* `p` = P(compra | clique). Desconhecido. É a média da posterior Beta(α, β), com prior
  vindo da categoria e evidência própria vinda dos cliques e vendas medidos.

O que `opp_v2` não consegue fazer e isto faz: com `COMMISSION_SATURATION_BRL = 30`, um
produto de R$ 3 de comissão com 50 mil vendas empata com um de R$ 34 com 14 mil. Em
receita esperada eles não empatam nem de longe.

### Sobre o prior, e sobre ser honesto a respeito dele

Sem clique medido, `p` não é medição — é prior. Um prior achatado (o mesmo para todos)
reduziria o ranking a "maior comissão em dinheiro", e aí o topo de toda lista seria iPhone
de R$ 9.149: R$ 366 por venda e conversão pífima vinda de rede social. Então o prior é
MOLDADO pelo que a API informa, com fatores:

* monótonos e limitados, cada um com a faixa declarada abaixo;
* neutros (1.0) quando o dado não veio — ausência nunca penaliza;
* dominados pela evidência própria a partir de `PRIOR_STRENGTH` cliques.

`prior_source` e todos os fatores vão para `components`, então qualquer número aqui é
auditável e substituível por medição.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from app.domain import beta_dist

ALGORITHM_VERSION = "ev_v1"

# CVR de partida de clique de afiliado. NÃO é medição nossa: é o ponto de partida até a
# Fase 0 medir o nosso (docs/plano-10k.md §1).
GLOBAL_CVR_PRIOR = Decimal("0.02")
# Força do prior, em cliques equivalentes. Com 200 cliques próprios a evidência já pesa
# metade; com 2.000, o prior é ruído de fundo.
PRIOR_STRENGTH = Decimal("200")
CVR_FLOOR = Decimal("0.0005")
CVR_CEILING = Decimal("0.15")

# Preço de referência do fator de preço e expoente da queda. Regularidade empírica mais
# robusta do e-commerce: conversão cai com o preço (mais consideração, mais comparação).
PRICE_REFERENCE = Decimal("50.00")
PRICE_ELASTICITY = 0.5
PRICE_FACTOR_FLOOR = Decimal("0.05")

# Demanda: mesmo log do opp_v2, mapeado em [0.5, 1.5]. Produto que vende muito no
# marketplace converte melhor com qualquer tráfego.
DEMAND_SATURATION_SALES = 5000

# Nota: [0.8, 1.1] entre 3 e 5 estrelas.
RATING_FLOOR = Decimal("3")
RATING_FACTOR_MIN = Decimal("0.8")
RATING_FACTOR_MAX = Decimal("1.1")

# Momento relativo medido (aceleração das vendas), limitado a ±50% de efeito.
MOMENTUM_CAP = Decimal("0.5")

# Quantis da posterior: o de baixo decide manter/cortar, o de cima decide o que testar.
DECISION_QUANTILE = 0.10
EXPLORATION_QUANTILE = 0.90


@dataclass(frozen=True)
class CvrPrior:
    """Prior agregado de um nível da hierarquia (global, categoria, faixa de preço)."""

    mean: Decimal
    # Em cliques equivalentes; nunca ultrapassa PRIOR_STRENGTH.
    strength: Decimal
    source: str


@dataclass(frozen=True)
class EVInput:
    commission_value: Decimal | None
    price: Decimal | None
    sales_volume: int | None
    rating: Decimal | None
    # Momento relativo medido na série de snapshots (app/domain/momentum.py).
    momentum: Decimal | None = None
    # Evidência própria. Clique medido pelo nosso redirect, venda atribuída por sub_id.
    clicks: int = 0
    conversions: int = 0
    category_prior: CvrPrior | None = None


@dataclass(frozen=True)
class EVResult:
    ev_per_click: Decimal
    commission_value: Decimal
    cvr_estimate: Decimal
    cvr_lower: Decimal
    cvr_upper: Decimal
    alpha: Decimal
    beta: Decimal
    clicks: int
    conversions: int
    prior_source: str
    # True quando a estimativa tem amostra PRÓPRIA; False = ainda é prior vestido de número.
    data_available: bool
    components: dict


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _price_factor(price: Decimal | None) -> tuple[Decimal, str]:
    if price is None or price <= 0:
        return Decimal("1"), "sem preço: fator neutro"
    if price <= PRICE_REFERENCE:
        return Decimal("1"), f"preço <= R$ {PRICE_REFERENCE}"
    ratio = float(PRICE_REFERENCE / price) ** PRICE_ELASTICITY
    factor = _clamp(Decimal(str(ratio)), PRICE_FACTOR_FLOOR, Decimal("1"))
    return factor.quantize(Decimal("0.0001")), f"(R$ {PRICE_REFERENCE}/preço)^{PRICE_ELASTICITY}"


def _demand_factor(sales_volume: int | None) -> tuple[Decimal, str]:
    if sales_volume is None:
        return Decimal("1"), "sem vendas informadas: fator neutro"
    ratio = math.log10(1 + max(sales_volume, 0)) / math.log10(1 + DEMAND_SATURATION_SALES)
    factor = Decimal("0.5") + _clamp(Decimal(str(ratio)), Decimal("0"), Decimal("1"))
    return factor.quantize(Decimal("0.0001")), "0,5 + log10(1+vendas)/log10(1+5000)"


def _rating_factor(rating: Decimal | None) -> tuple[Decimal, str]:
    if rating is None:
        return Decimal("1"), "sem nota: fator neutro"
    span = (RATING_FACTOR_MAX - RATING_FACTOR_MIN) / (Decimal("5") - RATING_FLOOR)
    factor = RATING_FACTOR_MIN + _clamp(rating - RATING_FLOOR, Decimal("0"), Decimal("2")) * span
    return factor.quantize(Decimal("0.0001")), "0,8 a 1,1 entre 3 e 5 estrelas"


def _momentum_factor(momentum: Decimal | None) -> tuple[Decimal, str]:
    if momentum is None:
        return Decimal("1"), "sem série suficiente: fator neutro"
    factor = Decimal("1") + _clamp(momentum, -MOMENTUM_CAP, MOMENTUM_CAP)
    return factor.quantize(Decimal("0.0001")), "1 + momento relativo, limitado a ±0,5"


def cvr_prior(data: EVInput) -> tuple[Decimal, str, dict]:
    """(média do prior, origem, fatores). A origem diz de onde veio a base."""
    base = data.category_prior.mean if data.category_prior else GLOBAL_CVR_PRIOR
    source = data.category_prior.source if data.category_prior else "global"

    price, price_why = _price_factor(data.price)
    demand, demand_why = _demand_factor(data.sales_volume)
    rating, rating_why = _rating_factor(data.rating)
    moment, moment_why = _momentum_factor(data.momentum)

    raw = base * price * demand * rating * moment
    mean = _clamp(raw, CVR_FLOOR, CVR_CEILING)
    factors = {
        "base": {"value": str(base), "source": source},
        "price": {"value": str(price), "rule": price_why},
        "demand": {"value": str(demand), "rule": demand_why},
        "rating": {"value": str(rating), "rule": rating_why},
        "momentum": {"value": str(moment), "rule": moment_why},
        "clamped": raw != mean,
    }
    return mean.quantize(Decimal("0.000001")), source, factors


def compute(data: EVInput) -> EVResult | None:
    """None quando a comissão em dinheiro não é conhecida: sem `r` não há EV.

    Receita por clique não se estima sem saber quanto a venda paga — e a Shopee informa
    preço e taxa, então aqui ausência é falha de coleta, não característica da fonte.
    """
    if data.commission_value is None:
        return None

    prior_mean, source, factors = cvr_prior(data)
    strength = (
        min(data.category_prior.strength, PRIOR_STRENGTH)
        if data.category_prior
        else PRIOR_STRENGTH
    )

    alpha_0 = prior_mean * strength
    beta_0 = (Decimal("1") - prior_mean) * strength
    conversions = max(0, min(data.conversions, data.clicks)) if data.clicks else 0
    alpha = alpha_0 + conversions
    beta = beta_0 + max(0, data.clicks - conversions)

    a, b = float(alpha), float(beta)
    estimate = Decimal(str(beta_dist.mean(a, b)))
    lower = Decimal(str(beta_dist.quantile(DECISION_QUANTILE, a, b)))
    upper = Decimal(str(beta_dist.quantile(EXPLORATION_QUANTILE, a, b)))

    ev = (data.commission_value * estimate).quantize(Decimal("0.000001"))
    return EVResult(
        ev_per_click=ev,
        commission_value=data.commission_value,
        cvr_estimate=estimate.quantize(Decimal("0.000001")),
        cvr_lower=lower.quantize(Decimal("0.000001")),
        cvr_upper=upper.quantize(Decimal("0.000001")),
        alpha=alpha.quantize(Decimal("0.0001")),
        beta=beta.quantize(Decimal("0.0001")),
        clicks=data.clicks,
        conversions=conversions,
        prior_source=source,
        # Prior vestido de número não é dado disponível: com zero clique a estimativa é
        # uma hipótese, e quem decide corte precisa saber disso.
        data_available=data.clicks > 0,
        components={
            "commission_value": str(data.commission_value),
            "prior_mean": str(prior_mean),
            "prior_strength": str(strength),
            "prior_factors": factors,
            "evidence": {"clicks": data.clicks, "conversions": conversions},
            "quantiles": {
                "decision": str(DECISION_QUANTILE),
                "exploration": str(EXPLORATION_QUANTILE),
            },
        },
    )
