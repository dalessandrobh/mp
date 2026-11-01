"""Opportunity Score estatístico (opp_v1). Função pura, sem LLM e sem banco.

Cada componente vai de 0 a 100 e só existe se o dado veio da API. Componente
sem dado sai da conta e os pesos restantes são renormalizados — o contrário
seria tratar "não sei" como "zero" e rebaixar produto por falta de medição.
O score só é decisório (`data_available=True`) quando todos os componentes
estão presentes; caso contrário é indicativo.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from app.domain import formulas

ALGORITHM_VERSION = "opp_v1"

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


def _component_values(data: OpportunityInput) -> dict[str, Decimal | None]:
    demand = None
    if data.sales_volume is not None:
        ratio = math.log10(1 + data.sales_volume) / math.log10(1 + DEMAND_SATURATION_SALES)
        demand = _clamp(Decimal(str(ratio)) * 100)

    commission = None
    value = formulas.commission_value(data.price, data.commission_rate)
    if value is not None:
        commission = _clamp(value / COMMISSION_SATURATION_BRL * 100)

    social_proof = None
    if data.rating is not None and data.rating_count is not None:
        quality = _clamp((data.rating - RATING_FLOOR) / (5 - RATING_FLOOR) * 100)
        confidence = min(Decimal(1), Decimal(data.rating_count) / RATING_COUNT_FOR_FULL_CONFIDENCE)
        social_proof = quality * confidence

    availability = None
    if data.stock is not None:
        availability = _clamp(Decimal(data.stock) / STOCK_SATURATION * 100)

    return {
        "demand": demand,
        "commission": commission,
        "social_proof": social_proof,
        "availability": availability,
    }


def compute(data: OpportunityInput) -> OpportunityResult | None:
    """None quando nenhum componente tem dado: não há o que pontuar."""
    values = _component_values(data)
    present = {name: value for name, value in values.items() if value is not None}
    if not present:
        return None

    weight_sum = sum(WEIGHTS[name] for name in present)
    score = sum(value * WEIGHTS[name] for name, value in present.items()) / weight_sum

    missing = tuple(name for name, value in values.items() if value is None)
    components = {
        name: {
            "value": str(value.quantize(Decimal("0.001"))) if value is not None else None,
            "weight": str(WEIGHTS[name]),
            "available": value is not None,
        }
        for name, value in values.items()
    }
    return OpportunityResult(
        score=score.quantize(Decimal("0.001")),
        data_available=not missing,
        missing_fields=missing,
        components=components,
    )
