"""Performance Score por produto e janela. Append-only; não regrava score idêntico."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import formulas, performance_score
from app.domain.enums import SettlementStatus
from app.domain.performance_score import PerformanceInput
from app.models.metrics import PerformanceDaily
from app.models.scoring import PerformanceScore
from app.services.portfolio_service import PortfolioParams

WINDOWS = (7, 30)
_ORDER = {
    SettlementStatus.PROVISIONAL: 0,
    SettlementStatus.PARTIAL: 1,
    SettlementStatus.SETTLED: 2,
}


@dataclass
class PerformanceScoringResult:
    scored: int = 0
    unchanged: int = 0
    skipped_no_data: int = 0
    warnings: list[str] = field(default_factory=list)


def _sum(rows, attr):
    values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return sum(values) if values else None


def run_performance_scoring(
    db: Session, params: PortfolioParams, *, today=None
) -> PerformanceScoringResult:
    today = today or datetime.now(UTC).date()
    result = PerformanceScoringResult()

    for window in WINDOWS:
        since = today - timedelta(days=window - 1)
        rows_by_product: dict[int, list[PerformanceDaily]] = {}
        for row in db.execute(
            select(PerformanceDaily)
            .where(PerformanceDaily.metric_date >= since, PerformanceDaily.metric_date <= today)
            .order_by(PerformanceDaily.product_id, PerformanceDaily.metric_date)
        ).scalars():
            rows_by_product.setdefault(row.product_id, []).append(row)

        for product_id, rows in rows_by_product.items():
            clicks, impressions = _sum(rows, "clicks"), _sum(rows, "impressions")
            conversions = _sum(rows, "conversions")
            # ROI da janela só existe se há receita E custo medidos em algum dia.
            measured = [r for r in rows if r.revenue_data_available and r.cost_data_available]
            revenue, spend = _sum(measured, "revenue"), _sum(measured, "ad_spend")

            computed = performance_score.compute(
                PerformanceInput(
                    roi=formulas.roi(revenue, spend),
                    ctr=formulas.ctr(clicks, impressions),
                    cvr=formulas.cvr(conversions, clicks) if measured else None,
                    daily_rois=tuple(r.roi for r in measured if r.roi is not None),
                )
            )
            if computed is None:
                result.skipped_no_data += 1
                continue

            settlement = min((r.settlement for r in rows), key=_ORDER.__getitem__)
            sufficient = formulas.is_sample_sufficient(
                clicks,
                impressions,
                min_clicks=params.min_clicks_for_decision,
                min_impressions=params.min_impressions_for_decision,
            )

            latest = db.execute(
                select(PerformanceScore)
                .where(
                    PerformanceScore.product_id == product_id,
                    PerformanceScore.window_days == window,
                )
                .order_by(PerformanceScore.computed_at.desc(), PerformanceScore.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if (
                latest is not None
                and latest.algorithm_version == performance_score.ALGORITHM_VERSION
                and latest.score == computed.score
                and latest.components == computed.components
                and latest.sample_sufficient == sufficient
                and latest.settlement == settlement
            ):
                result.unchanged += 1
                continue

            db.add(
                PerformanceScore(
                    product_id=product_id,
                    window_days=window,
                    score=computed.score,
                    algorithm_version=performance_score.ALGORITHM_VERSION,
                    components=computed.components,
                    data_available=computed.data_available,
                    sample_sufficient=sufficient,
                    settlement=settlement,
                )
            )
            result.scored += 1

    db.flush()
    return result


