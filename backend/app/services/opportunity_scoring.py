"""Opportunity Score estatístico (sem LLM).

Cada componente é normalizado para 0..1 contra tetos FIXOS, não contra o
min/max do lote: assim o score de um produto não muda só porque outro produto
entrou na busca, e scores de dias diferentes continuam comparáveis.

Componente sem dado fica fora da média (os pesos dos presentes são
renormalizados) e entra em `missing_fields`. Se faltar comissão ou vendas, o
score sai como `data_available=False`: indicativo, não decisório.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.adapters.marketplace.base import MarketplaceProduct

ALGORITHM_VERSION = "v1-stat"

# Pesos relativos; só importam entre si.
WEIGHTS: dict[str, float] = {
    "commission": 1.0,
    "sales": 1.0,
    "rating": 1.0,
    "commission_value": 1.0,
    "shop_trust": 1.0,
    "discount": 1.0,
    "time": 1.0,
}

# Sem esses dois o score não sustenta decisão.
REQUIRED = ("commission", "sales")

_COMMISSION_CAP = 0.20  # 20% já é teto de mercado
_SALES_CAP = 10_000
_VALUE_CAP = 50.0  # R$ por venda
_DISCOUNT_CAP = 50


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal
    components: dict[str, float | None]
    data_available: bool
    missing_fields: list[str]
    algorithm_version: str = ALGORITHM_VERSION


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _shop_trust(shop_types: tuple[int, ...]) -> float:
    if 1 in shop_types:
        return 1.0
    if 4 in shop_types:
        return 0.8
    if 2 in shop_types:
        return 0.6
    return 0.5


def _time_factor(period_end: datetime | None, now: datetime) -> float | None:
    if period_end is None:
        return None
    days = (period_end - now).total_seconds() / 86400
    if days <= 0:
        return 0.0
    if days < 7:
        return 0.2
    if days <= 30:
        return 0.5
    return 1.0


def compute_opportunity_score(
    product: MarketplaceProduct, *, now: datetime | None = None
) -> ScoreResult:
    now = now or datetime.now(UTC)

    components: dict[str, float | None] = {
        "commission": (
            None
            if product.commission_rate is None
            else _clip(float(product.commission_rate) / _COMMISSION_CAP)
        ),
        # Escala log: 10 vendas -> 100 é salto parecido com 1000 -> 10000.
        "sales": (
            None
            if product.sales is None
            else _clip(math.log1p(product.sales) / math.log1p(_SALES_CAP))
        ),
        "rating": None if product.rating is None else _clip(float(product.rating) / 5),
        "commission_value": (
            None
            if product.commission_value is None
            else _clip(float(product.commission_value) / _VALUE_CAP)
        ),
        "shop_trust": _shop_trust(product.shop_types),
        "discount": (
            None if product.discount_rate is None else _clip(product.discount_rate / _DISCOUNT_CAP)
        ),
        "time": _time_factor(product.period_end, now),
    }

    present = {k: v for k, v in components.items() if v is not None}
    missing = [k for k, v in components.items() if v is None]

    total_weight = sum(WEIGHTS[k] for k in present)
    if total_weight == 0:
        raw = 0.0
    else:
        raw = sum(WEIGHTS[k] * v for k, v in present.items()) / total_weight

    return ScoreResult(
        score=Decimal(str(round(raw * 100, 3))),
        components=components,
        data_available=not any(k in missing for k in REQUIRED),
        missing_fields=missing,
    )
