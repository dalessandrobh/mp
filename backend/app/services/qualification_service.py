"""Qualificação: aplica os filtros duros aos produtos em DISCOVERY."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.enums import ProductState
from app.domain.qualification import (
    QualificationCriteria,
    QualificationInput,
    QualificationOutcome,
    evaluate,
)
from app.domain.state_machine import transition
from app.services import config_params
from app.services._funnel_queries import latest_snapshot, products_in_state

ACTOR = "system"


@dataclass
class QualificationResult:
    evaluated: int = 0
    qualified: int = 0
    rejected: int = 0
    waiting: int = 0
    warnings: list[str] = field(default_factory=list)


def load_criteria(db: Session) -> QualificationCriteria:
    defaults = QualificationCriteria()
    return QualificationCriteria(
        min_price=config_params.get_decimal(db, "QUALIFICATION_MIN_PRICE", defaults.min_price),
        min_commission_rate=config_params.get_decimal(
            db, "QUALIFICATION_MIN_COMMISSION_RATE", defaults.min_commission_rate
        ),
        min_commission_value=config_params.get_decimal(
            db, "QUALIFICATION_MIN_COMMISSION_VALUE", defaults.min_commission_value
        ),
        min_rating=config_params.get_decimal(db, "QUALIFICATION_MIN_RATING", defaults.min_rating),
        min_rating_count=config_params.get_int(
            db, "QUALIFICATION_MIN_RATING_COUNT", defaults.min_rating_count
        ),
    )


def run_qualification(db: Session) -> QualificationResult:
    criteria = load_criteria(db)
    result = QualificationResult()

    for product in products_in_state(db, ProductState.DISCOVERY):
        snapshot = latest_snapshot(db, product.id)
        if snapshot is None:
            result.waiting += 1
            result.warnings.append(f"produto {product.id} sem snapshot")
            continue

        verdict = evaluate(
            QualificationInput(
                price=snapshot.price,
                commission_rate=snapshot.commission_rate,
                rating=snapshot.rating,
                rating_count=snapshot.rating_count,
                stock=snapshot.stock,
            ),
            criteria,
        )
        result.evaluated += 1

        if verdict.outcome is QualificationOutcome.WAIT:
            result.waiting += 1
            continue

        target = (
            ProductState.QUALIFICATION
            if verdict.outcome is QualificationOutcome.QUALIFY
            else ProductState.REJECTED
        )
        transition(
            db,
            product_id=product.id,
            to_state=target,
            reason_code=verdict.reason_code,
            actor=ACTOR,
            metrics_used={
                "snapshot_id": snapshot.id,
                "failed_checks": list(verdict.failed_checks),
                "criteria": {k: str(v) for k, v in vars(criteria).items()},
            },
        )
        if target is ProductState.QUALIFICATION:
            result.qualified += 1
        else:
            result.rejected += 1

    return result



