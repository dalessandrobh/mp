"""calculateOptimalPortfolioSize(): quantos produtos o orçamento sustenta.

É RECOMMEND — devolve número e pressupostos, não executa nada. Sem CPC
observado não há como estimar quanto tempo um teste leva para decidir; nesse
caso o resultado vem sem tamanho único (`data_available=False`) e com uma
faixa, em vez de um número inventado.
"""

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SizingInput:
    max_daily_ad_spend: Decimal
    min_daily_test_budget: Decimal
    exploration_percentage: int
    min_active_products: int
    max_active_products: int
    min_clicks_for_decision: int
    avg_cpc: Decimal | None


@dataclass(frozen=True)
class SizingResult:
    data_available: bool
    # None quando falta CPC: só a faixa é honesta.
    recommended_size: int | None
    range_min: int
    range_max: int
    exploration_slots: int
    exploitation_slots: int
    days_to_decision: Decimal | None
    feasible: bool
    assumptions: dict
    warnings: tuple[str, ...]


def compute_sizing(data: SizingInput) -> SizingResult:
    exploration_budget = data.max_daily_ad_spend * data.exploration_percentage / 100
    exploitation_budget = data.max_daily_ad_spend - exploration_budget

    exploration_slots = math.floor(exploration_budget / data.min_daily_test_budget)
    exploitation_slots = math.floor(exploitation_budget / data.min_daily_test_budget)
    capacity = exploration_slots + exploitation_slots

    range_max = min(capacity, data.max_active_products)
    feasible = capacity >= data.min_active_products
    range_min = min(data.min_active_products, range_max)

    warnings: list[str] = []
    if not feasible:
        warnings.append(
            f"orçamento sustenta {capacity} produto(s), abaixo do piso de "
            f"{data.min_active_products}"
        )

    days_to_decision = None
    recommended = None
    if data.avg_cpc is not None and data.avg_cpc > 0:
        clicks_per_day = data.min_daily_test_budget / data.avg_cpc
        days_to_decision = (data.min_clicks_for_decision / clicks_per_day).quantize(
            Decimal("0.1")
        )
        recommended = range_max
    else:
        warnings.append("CPC médio ainda não observado: devolvendo faixa, sem tamanho único")

    return SizingResult(
        data_available=recommended is not None,
        recommended_size=recommended,
        range_min=range_min,
        range_max=range_max,
        exploration_slots=exploration_slots,
        exploitation_slots=exploitation_slots,
        days_to_decision=days_to_decision,
        feasible=feasible,
        assumptions={
            "max_daily_ad_spend": str(data.max_daily_ad_spend),
            "min_daily_test_budget": str(data.min_daily_test_budget),
            "exploration_percentage": data.exploration_percentage,
            "min_clicks_for_decision": data.min_clicks_for_decision,
            "avg_cpc": str(data.avg_cpc) if data.avg_cpc is not None else None,
            "exploration_budget": str(exploration_budget),
            "exploitation_budget": str(exploitation_budget),
        },
        warnings=tuple(warnings),
    )
