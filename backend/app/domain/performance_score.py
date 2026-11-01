"""Performance Score (perf_v1). Separado do Opportunity Score: aquele prevê, este mede.

Mesma disciplina do Opportunity: componente sem dado sai da conta, os pesos
restantes são renormalizados, e o score só é completo (`data_available`)
quando todos os componentes existem.

CPC e ROAS não entram como componentes: o ROAS é transformação monótona do ROI
(contá-lo dobraria o peso do mesmo sinal) e o CPC não tem benchmark absoluto
ainda — ele aparece no diagnóstico (zones) e no sizing, não aqui.
"""

import statistics
from dataclasses import dataclass
from decimal import Decimal

from app.domain.zones import CTR_GOOD, CVR_GOOD

ALGORITHM_VERSION = "perf_v1"

WEIGHTS = {
    "roi": Decimal("0.45"),
    "cvr": Decimal("0.20"),
    "ctr": Decimal("0.15"),
    "stability": Decimal("0.20"),
}
MIN_DAYS_FOR_STABILITY = 3


@dataclass(frozen=True)
class PerformanceInput:
    roi: Decimal | None
    ctr: Decimal | None
    cvr: Decimal | None
    # ROI de cada dia da janela que o tem medido.
    daily_rois: tuple[Decimal, ...]


@dataclass(frozen=True)
class PerformanceResult:
    score: Decimal
    data_available: bool
    missing_fields: tuple[str, ...]
    components: dict


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(100), value))


def _component_values(data: PerformanceInput) -> dict[str, Decimal | None]:
    # ROI -100% => 0, empate => 50, +100% ou mais => 100.
    roi = _clamp((data.roi + 1) / 2 * 100) if data.roi is not None else None
    cvr = _clamp(data.cvr / (CVR_GOOD * 2) * 100) if data.cvr is not None else None
    ctr = _clamp(data.ctr / (CTR_GOOD * 2) * 100) if data.ctr is not None else None

    stability = None
    if len(data.daily_rois) >= MIN_DAYS_FOR_STABILITY:
        deviation = Decimal(str(statistics.pstdev(float(r) for r in data.daily_rois)))
        # Desvio de 1,0 (100 pontos de ROI) ou mais zera a estabilidade.
        stability = _clamp(100 - deviation * 100)

    return {"roi": roi, "cvr": cvr, "ctr": ctr, "stability": stability}


def compute(data: PerformanceInput) -> PerformanceResult | None:
    values = _component_values(data)
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return None

    weight_sum = sum(WEIGHTS[k] for k in present)
    score = sum(v * WEIGHTS[k] for k, v in present.items()) / weight_sum
    missing = tuple(k for k, v in values.items() if v is None)

    return PerformanceResult(
        score=score.quantize(Decimal("0.001")),
        data_available=not missing,
        missing_fields=missing,
        components={
            name: {
                "value": str(v.quantize(Decimal("0.001"))) if v is not None else None,
                "weight": str(WEIGHTS[name]),
                "available": v is not None,
            }
            for name, v in values.items()
        },
    )
