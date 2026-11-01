from decimal import Decimal

from app.domain.qualification import (
    QualificationCriteria,
    QualificationInput,
    QualificationOutcome,
    evaluate,
)

CRITERIA = QualificationCriteria()


def _input(**overrides) -> QualificationInput:
    base = dict(
        price=Decimal("50"),
        commission_rate=Decimal("0.08"),
        rating=Decimal("4.7"),
        rating_count=120,
        stock=40,
    )
    return QualificationInput(**{**base, **overrides})


def test_healthy_product_qualifies():
    assert evaluate(_input(), CRITERIA).outcome is QualificationOutcome.QUALIFY


def test_missing_price_or_commission_waits_instead_of_rejecting():
    for field in ("price", "commission_rate"):
        result = evaluate(_input(**{field: None}), CRITERIA)
        assert result.outcome is QualificationOutcome.WAIT


def test_rejections_carry_the_reason():
    cases = {
        "OUT_OF_STOCK": dict(stock=0),
        "PRICE_TOO_LOW": dict(price=Decimal("5")),
        "COMMISSION_TOO_LOW": dict(commission_rate=Decimal("0.01")),
        "LOW_RATING": dict(rating=Decimal("3.1")),
    }
    for reason, overrides in cases.items():
        result = evaluate(_input(**overrides), CRITERIA)
        assert result.outcome is QualificationOutcome.REJECT
        assert result.reason_code == reason


def test_low_rating_with_few_reviews_is_ignored():
    result = evaluate(_input(rating=Decimal("2.0"), rating_count=3), CRITERIA)

    assert result.outcome is QualificationOutcome.QUALIFY


def test_unknown_stock_and_rating_do_not_reject():
    result = evaluate(_input(stock=None, rating=None, rating_count=None), CRITERIA)

    assert result.outcome is QualificationOutcome.QUALIFY
