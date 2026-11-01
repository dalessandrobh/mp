from decimal import Decimal

from app.domain import opportunity
from app.domain.opportunity import OpportunityInput


def _input(**overrides) -> OpportunityInput:
    base = dict(
        price=Decimal("400"),
        commission_rate=Decimal("0.10"),
        rating=Decimal("5"),
        rating_count=200,
        sales_volume=5000,
        stock=100,
    )
    return OpportunityInput(**{**base, **overrides})


def test_saturated_product_scores_100_and_is_decisive():
    result = opportunity.compute(_input())

    assert result.score == Decimal("100.000")
    assert result.data_available is True
    assert result.missing_fields == ()


def test_missing_component_is_dropped_not_zeroed():
    full = opportunity.compute(_input())
    without_sales = opportunity.compute(_input(sales_volume=None))

    # Tudo o mais saturado: tirar vendas não pode derrubar o score.
    assert without_sales.score == full.score
    assert without_sales.data_available is False
    assert without_sales.missing_fields == ("demand",)
    assert without_sales.components["demand"]["available"] is False


def test_zero_sales_is_measured_and_differs_from_missing():
    zero = opportunity.compute(_input(sales_volume=0))
    missing = opportunity.compute(_input(sales_volume=None))

    assert zero.score < missing.score
    assert zero.data_available is True


def test_no_data_at_all_returns_none():
    empty = OpportunityInput(None, None, None, None, None, None)

    assert opportunity.compute(empty) is None


def test_few_reviews_discount_a_perfect_rating():
    confident = opportunity.compute(_input(rating_count=100))
    shaky = opportunity.compute(_input(rating_count=5))

    assert shaky.score < confident.score
