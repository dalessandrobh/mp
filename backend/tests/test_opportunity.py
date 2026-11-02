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


# ---------- opp_v2: ausência estrutural (marketplace que nunca informa o campo) ----------

SHOPEE_LIKE = frozenset({"stock", "rating_count", "original_price"})


def test_a_field_the_marketplace_never_reports_does_not_make_the_score_indicative():
    data = _input(stock=None, rating_count=None)

    structural = opportunity.compute(data, unsupported=SHOPEE_LIKE)
    plain = opportunity.compute(data)

    assert structural.data_available is True and structural.missing_fields == ()
    assert plain.data_available is False  # sem declarar, o mesmo dado continua sendo "falta"


def test_structural_absence_leaves_the_component_out_of_the_weighted_score():
    full = opportunity.compute(_input())
    without_stock = opportunity.compute(_input(stock=None), unsupported=frozenset({"stock"}))

    assert without_stock.components["availability"]["reason"] == "unsupported"
    assert without_stock.score == full.score  # tudo saturado: tirar um componente não rebaixa


def test_without_review_count_confidence_comes_from_sales():
    popular = opportunity.compute(_input(rating_count=None, sales_volume=5000),
                                  unsupported=SHOPEE_LIKE)
    barely_sold = opportunity.compute(_input(rating_count=None, sales_volume=3),
                                      unsupported=SHOPEE_LIKE)

    assert popular.components["social_proof"]["note"] == "sales_proxy"
    low = Decimal(barely_sold.components["social_proof"]["value"])
    high = Decimal(popular.components["social_proof"]["value"])
    assert low < high


def test_unsupported_review_count_with_no_sales_is_a_real_gap_not_a_structural_one():
    result = opportunity.compute(_input(rating_count=None, sales_volume=None),
                                 unsupported=SHOPEE_LIKE)

    assert "social_proof" in result.missing_fields and "demand" in result.missing_fields
    assert result.data_available is False


def test_a_field_that_can_be_reported_but_is_missing_still_counts_as_missing():
    result = opportunity.compute(_input(sales_volume=None), unsupported=SHOPEE_LIKE)

    assert result.missing_fields == ("demand",) and result.data_available is False
