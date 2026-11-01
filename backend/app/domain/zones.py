"""Classificação de produtos ativos em zonas de desempenho e diagnóstico (§8.1/§8.2).

Duas proteções atravessam o módulo: sem dado de receita é NO_DATA, e sem
amostra madura ou dado liquidado (SETTLED) ninguém é UNDERPERFORMER. Julgar mau
desempenho com dado provisório ou escasso é como o motor cortaria produto bom.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.enums import SettlementStatus

# Benchmarks do diagnóstico. Valores de partida; viram parâmetros quando houver histórico.
CTR_GOOD = Decimal("0.01")
CVR_GOOD = Decimal("0.02")
WINNER_MIN_ROI = Decimal("0.2")


class Zone(StrEnum):
    WINNER = "WINNER"
    PROMISING = "PROMISING"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNDERPERFORMER = "UNDERPERFORMER"
    NO_DATA = "NO_DATA"


class Diagnosis(StrEnum):
    CREATIVE_WEAK = "CREATIVE_WEAK"
    OFFER_WEAK = "OFFER_WEAK"
    COMMISSION_INSUFFICIENT = "COMMISSION_INSUFFICIENT"
    HEALTHY = "HEALTHY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ZoneInput:
    clicks: int | None
    impressions: int | None
    roi: Decimal | None
    revenue_data_available: bool
    settlement: SettlementStatus
    days_in_test: int


@dataclass(frozen=True)
class ZoneThresholds:
    min_clicks: int
    min_impressions: int
    min_test_duration_days: int


def classify(data: ZoneInput, limits: ZoneThresholds) -> Zone:
    if not data.revenue_data_available or data.clicks is None or data.roi is None:
        return Zone.NO_DATA

    mature = (
        data.days_in_test >= limits.min_test_duration_days
        and data.clicks >= limits.min_clicks
        and data.impressions is not None
        and data.impressions >= limits.min_impressions
    )
    if not mature:
        return Zone.PROMISING if data.roi > 0 else Zone.INCONCLUSIVE

    if data.roi < 0:
        # Veredito negativo é destrutivo: só com comissão final, nunca provisória.
        return Zone.UNDERPERFORMER if data.settlement is SettlementStatus.SETTLED else (
            Zone.INCONCLUSIVE
        )
    return Zone.WINNER if data.roi >= WINNER_MIN_ROI else Zone.PROMISING


def diagnose(
    *, ctr: Decimal | None, cvr: Decimal | None, roi: Decimal | None
) -> Diagnosis:
    if ctr is None or cvr is None or roi is None:
        return Diagnosis.INSUFFICIENT_DATA
    if roi >= 0:
        return Diagnosis.HEALTHY
    if ctr < CTR_GOOD:
        return Diagnosis.CREATIVE_WEAK
    if cvr < CVR_GOOD:
        return Diagnosis.OFFER_WEAK
    return Diagnosis.COMMISSION_INSUFFICIENT
