"""Filtros duros do funil (DISCOVERY -> QUALIFICATION). Regra pura, sem banco.

Três desfechos, e o terceiro importa: dado ausente nunca reprova nem aprova.
Faltando preço ou comissão o produto espera (WAIT) — rejeitar por dado que a
API não informou seria punir ausência de medição como se fosse mau desempenho.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class QualificationOutcome(StrEnum):
    QUALIFY = "QUALIFY"
    REJECT = "REJECT"
    WAIT = "WAIT"


@dataclass(frozen=True)
class QualificationCriteria:
    min_price: Decimal = Decimal("10.00")
    min_commission_rate: Decimal = Decimal("0.03")
    min_rating: Decimal = Decimal("4.0")
    # Nota alta com poucas avaliações não é evidência; abaixo disso ignoramos a nota.
    min_rating_count: int = 10


@dataclass(frozen=True)
class QualificationInput:
    price: Decimal | None
    commission_rate: Decimal | None
    rating: Decimal | None
    rating_count: int | None
    stock: int | None


@dataclass(frozen=True)
class QualificationResult:
    outcome: QualificationOutcome
    reason_code: str
    failed_checks: tuple[str, ...] = ()


def evaluate(data: QualificationInput, criteria: QualificationCriteria) -> QualificationResult:
    if data.price is None or data.commission_rate is None:
        return QualificationResult(QualificationOutcome.WAIT, "MISSING_CORE_DATA")

    failed: list[str] = []

    if data.stock is not None and data.stock <= 0:
        failed.append("OUT_OF_STOCK")
    if data.price < criteria.min_price:
        failed.append("PRICE_TOO_LOW")
    if data.commission_rate < criteria.min_commission_rate:
        failed.append("COMMISSION_TOO_LOW")
    if (
        data.rating is not None
        and data.rating_count is not None
        and data.rating_count >= criteria.min_rating_count
        and data.rating < criteria.min_rating
    ):
        failed.append("LOW_RATING")

    if failed:
        return QualificationResult(QualificationOutcome.REJECT, failed[0], tuple(failed))
    return QualificationResult(QualificationOutcome.QUALIFY, "PASSED_HARD_FILTERS")
