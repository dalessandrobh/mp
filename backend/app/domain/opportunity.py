"""Opportunity Score estatístico (opp_v2). Função pura, sem LLM e sem banco.

Cada componente vai de 0 a 100 e só existe se o dado veio da API. Componente
sem dado sai da conta e os pesos restantes são renormalizados — o contrário
seria tratar "não sei" como "zero" e rebaixar produto por falta de medição.
O score só é decisório (`data_available=True`) quando todos os componentes
estão presentes; caso contrário é indicativo.

opp_v2 distingue duas ausências. Dado que o marketplace PODE informar e não veio é falta
(`missing_fields`, score indicativo). Dado que o marketplace NUNCA informa (ex.: estoque e
número de avaliações na Shopee) é ausência estrutural: o componente fica fora da conta e
não torna o score indicativo — senão nenhum produto da Shopee seria promovido jamais.
Sem número de avaliações, a confiança da nota vem das vendas (avaliações nunca passam de
vendas), e isso fica registrado em `confidence_source`.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from app.domain import formulas

ALGORITHM_VERSION = "opp_v2"

# Pesos somam 1.0. Os tetos abaixo são o ponto em que o componente satura em 100.
WEIGHTS = {
    "demand": Decimal("0.35"),
    "commission": Decimal("0.30"),
    "social_proof": Decimal("0.20"),
    "availability": Decimal("0.15"),
}
DEMAND_SATURATION_SALES = 5000
COMMISSION_SATURATION_BRL = Decimal("30")
RATING_FLOOR = Decimal("3")
RATING_COUNT_FOR_FULL_CONFIDENCE = 100
STOCK_SATURATION = 50


@dataclass(frozen=True)
class OpportunityInput:
    price: Decimal | None
    commission_rate: Decimal | None
    rating: Decimal | None
    rating_count: int | None
    sales_volume: int | None
    stock: int | None


@dataclass(frozen=True)
class OpportunityResult:
    score: Decimal
    data_available: bool
    missing_fields: tuple[str, ...]
    components: dict


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(100), value))


def _component_values(
    data: OpportunityInput, unsupported: frozenset[str]
) -> tuple[dict[str, Decimal | None], dict[str, str]]:
    """(valores, motivo-da-ausência-estrutural por componente, + notas)."""
    structural: dict[str, str] = {}
    demand = None
    if data.sales_volume is not None:
        ratio = math.log10(1 + data.sales_volume) / math.log10(1 + DEMAND_SATURATION_SALES)
        demand = _clamp(Decimal(str(ratio)) * 100)

    commission = None
    value = formulas.commission_value(data.price, data.commission_rate)
    if value is not None:
        commission = _clamp(value / COMMISSION_SATURATION_BRL * 100)

    social_proof = None
    reviews = data.rating_count
    proxied = reviews is None and "rating_count" in unsupported and data.sales_volume is not None
    if proxied:
        reviews = data.sales_volume
    if data.rating is not None and reviews is not None:
        if proxied:
            structural["social_proof"] = "sales_proxy"
        quality = _clamp((data.rating - RATING_FLOOR) / (5 - RATING_FLOOR) * 100)
        confidence = min(Decimal(1), Decimal(reviews) / RATING_COUNT_FOR_FULL_CONFIDENCE)
        social_proof = quality * confidence

    availability = None
    if data.stock is not None:
        availability = _clamp(Decimal(data.stock) / STOCK_SATURATION * 100)
    elif "stock" in unsupported:
        structural["availability"] = "unsupported"

    values = {
        "demand": demand,
        "commission": commission,
        "social_proof": social_proof,
        "availability": availability,
    }
    return values, structural


def compute(
    data: OpportunityInput, *, unsupported: frozenset[str] = frozenset()
) -> OpportunityResult | None:
    """None quando nenhum componente tem dado: não há o que pontuar.

    `unsupported`: campos que o marketplace nunca informa (ver MarketplaceAdapter).
    """
    values, notes = _component_values(data, unsupported)
    present = {name: value for name, value in values.items() if value is not None}
    if not present:
        return None

    weight_sum = sum(WEIGHTS[name] for name in present)
    score = sum(value * WEIGHTS[name] for name, value in present.items()) / weight_sum

    # Ausência estrutural não é falta: o componente sai da conta sem tornar o score indicativo.
    structural_absent = {n for n, note in notes.items() if note == "unsupported"}
    missing = tuple(
        name for name, value in values.items() if value is None and name not in structural_absent
    )
    components = {
        name: {
            "value": str(value.quantize(Decimal("0.001"))) if value is not None else None,
            "weight": str(WEIGHTS[name]),
            "available": value is not None,
            **({"note": notes[name]} if name in notes else {}),
            **({"reason": "unsupported"} if name in structural_absent else {}),
        }
        for name, value in values.items()
    }
    return OpportunityResult(
        score=score.quantize(Decimal("0.001")),
        data_available=not missing,
        missing_fields=missing,
        components=components,
    )
