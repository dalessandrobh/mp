from decimal import Decimal

from app.domain.portfolio_sizer import SizingInput, compute_sizing


def _input(**overrides) -> SizingInput:
    base = dict(
        max_daily_ad_spend=Decimal("100"),
        min_daily_test_budget=Decimal("10"),
        exploration_percentage=30,
        min_active_products=3,
        max_active_products=15,
        min_clicks_for_decision=50,
        avg_cpc=Decimal("0.50"),
    )
    return SizingInput(**{**base, **overrides})


def test_slots_follow_the_budget_split():
    result = compute_sizing(_input())

    assert result.exploration_slots == 3
    assert result.exploitation_slots == 7
    assert result.recommended_size == 10
    assert result.feasible is True


def test_days_to_decision_uses_observed_cpc():
    # R$10/dia a R$0,50 por clique = 20 cliques/dia; 50 cliques = 2,5 dias.
    assert compute_sizing(_input()).days_to_decision == Decimal("2.5")


def test_without_cpc_returns_a_range_not_a_single_number():
    result = compute_sizing(_input(avg_cpc=None))

    assert result.data_available is False
    assert result.recommended_size is None
    assert result.days_to_decision is None
    assert (result.range_min, result.range_max) == (3, 10)
    assert any("CPC" in w for w in result.warnings)


def test_recommendation_is_capped_by_max_active_products():
    result = compute_sizing(_input(max_daily_ad_spend=Decimal("1000"), max_active_products=12))

    assert result.recommended_size == 12


def test_budget_below_the_floor_is_flagged_infeasible():
    result = compute_sizing(_input(max_daily_ad_spend=Decimal("20")))

    assert result.feasible is False
    assert result.warnings
