"""Opportunity Score e promoção a CANDIDATE.

O score é estatístico (opp_v2): nenhum dado sai para LLM aqui, e `llm_used`
fica sempre falso. Cada cálculo é uma linha nova — o score de ontem não é
reescrito.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import opportunity
from app.domain.enums import ProductState
from app.domain.opportunity import OpportunityInput
from app.domain.state_machine import transition
from app.models.catalog import Marketplace
from app.models.scoring import OpportunityScore
from app.services import config_params
from app.services._funnel_queries import latest_snapshot, products_in_state

ACTOR = "system"
DEFAULT_PROMOTION_MIN_SCORE = Decimal("50")


@dataclass
class ScoringResult:
    scored: int = 0
    skipped_up_to_date: int = 0
    skipped_no_data: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class PromotionResult:
    evaluated: int = 0
    promoted: int = 0
    held_low_score: int = 0
    held_indicative: int = 0
    held_unscored: int = 0


def latest_score(db: Session, product_id: int) -> OpportunityScore | None:
    return db.execute(
        select(OpportunityScore)
        .where(OpportunityScore.product_id == product_id)
        .order_by(OpportunityScore.computed_at.desc(), OpportunityScore.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _unsupported_fields(db: Session, marketplace_id: int, cache: dict[int, frozenset]) -> frozenset:
    """Campos que o marketplace do produto nunca informa (gravados na descoberta)."""
    if marketplace_id not in cache:
        config = db.execute(
            select(Marketplace.config).where(Marketplace.id == marketplace_id)
        ).scalar_one_or_none()
        cache[marketplace_id] = frozenset((config or {}).get("unsupported_fields", []))
    return cache[marketplace_id]


def run_opportunity_scoring(db: Session) -> ScoringResult:
    result = ScoringResult()
    unsupported_cache: dict[int, frozenset] = {}

    for product in products_in_state(db, ProductState.QUALIFICATION):
        snapshot = latest_snapshot(db, product.id)
        if snapshot is None:
            result.skipped_no_data += 1
            continue

        existing = latest_score(db, product.id)
        # Só recalcula quando há snapshot mais novo ou o algoritmo mudou.
        if (
            existing is not None
            and existing.algorithm_version == opportunity.ALGORITHM_VERSION
            and existing.computed_at >= snapshot.captured_at
        ):
            result.skipped_up_to_date += 1
            continue

        computed = opportunity.compute(
            OpportunityInput(
                price=snapshot.price,
                commission_rate=snapshot.commission_rate,
                rating=snapshot.rating,
                rating_count=snapshot.rating_count,
                sales_volume=snapshot.sales_volume,
                stock=snapshot.stock,
            ),
            unsupported=_unsupported_fields(db, product.marketplace_id, unsupported_cache),
        )
        if computed is None:
            result.skipped_no_data += 1
            result.warnings.append(f"produto {product.id} sem nenhum dado para pontuar")
            continue

        db.add(
            OpportunityScore(
                product_id=product.id,
                score=computed.score,
                algorithm_version=opportunity.ALGORITHM_VERSION,
                components=computed.components,
                data_available=computed.data_available,
                missing_fields=list(computed.missing_fields),
                llm_used=False,
            )
        )
        result.scored += 1

    db.flush()
    return result


def run_promotion(db: Session) -> PromotionResult:
    """QUALIFICATION -> CANDIDATE para quem tem score decisório acima do corte."""
    threshold = config_params.get_decimal(
        db, "PROMOTION_MIN_OPPORTUNITY_SCORE", DEFAULT_PROMOTION_MIN_SCORE
    )
    result = PromotionResult()

    for product in products_in_state(db, ProductState.QUALIFICATION):
        result.evaluated += 1
        score = latest_score(db, product.id)

        if score is None:
            result.held_unscored += 1
        elif not score.data_available:
            # Score indicativo não decide: falta dado, não sobra mérito.
            result.held_indicative += 1
        elif score.score < threshold:
            result.held_low_score += 1
        else:
            transition(
                db,
                product_id=product.id,
                to_state=ProductState.CANDIDATE,
                reason_code="OPPORTUNITY_SCORE_ABOVE_THRESHOLD",
                actor=ACTOR,
                metrics_used={
                    "score_id": score.id,
                    "score": str(score.score),
                    "threshold": str(threshold),
                    "algorithm_version": score.algorithm_version,
                },
            )
            result.promoted += 1

    return result
