from decimal import Decimal

from app.domain.enums import SettlementStatus
from app.domain.zones import Diagnosis, Zone, ZoneInput, ZoneThresholds, classify, diagnose

LIMITS = ZoneThresholds(min_clicks=50, min_impressions=1000, min_test_duration_days=3)


def _input(**overrides) -> ZoneInput:
    base = dict(
        clicks=200,
        impressions=5000,
        roi=Decimal("-0.4"),
        revenue_data_available=True,
        settlement=SettlementStatus.SETTLED,
        days_in_test=7,
    )
    return ZoneInput(**{**base, **overrides})


def test_settled_negative_roi_with_mature_sample_is_underperformer():
    assert classify(_input(), LIMITS) is Zone.UNDERPERFORMER


def test_provisional_data_never_condemns_a_product():
    result = classify(_input(settlement=SettlementStatus.PROVISIONAL), LIMITS)

    assert result is Zone.INCONCLUSIVE


def test_missing_revenue_is_no_data_not_underperformer():
    assert classify(_input(revenue_data_available=False, roi=None), LIMITS) is Zone.NO_DATA


def test_immature_sample_is_never_underperformer():
    for overrides in (dict(clicks=10), dict(impressions=100), dict(days_in_test=1)):
        assert classify(_input(**overrides), LIMITS) is Zone.INCONCLUSIVE


def test_positive_but_immature_is_promising():
    assert classify(_input(clicks=10, roi=Decimal("0.3")), LIMITS) is Zone.PROMISING


def test_strong_mature_roi_is_winner():
    assert classify(_input(roi=Decimal("0.5")), LIMITS) is Zone.WINNER


def test_diagnosis_table():
    assert diagnose(ctr=Decimal("0.002"), cvr=Decimal("0.05"), roi=Decimal("-0.3")) is (
        Diagnosis.CREATIVE_WEAK
    )
    assert diagnose(ctr=Decimal("0.02"), cvr=Decimal("0.005"), roi=Decimal("-0.3")) is (
        Diagnosis.OFFER_WEAK
    )
    assert diagnose(ctr=Decimal("0.02"), cvr=Decimal("0.05"), roi=Decimal("-0.3")) is (
        Diagnosis.COMMISSION_INSUFFICIENT
    )
    assert diagnose(ctr=Decimal("0.02"), cvr=Decimal("0.05"), roi=Decimal("0.3")) is (
        Diagnosis.HEALTHY
    )
    assert diagnose(ctr=None, cvr=Decimal("0.05"), roi=Decimal("-0.3")) is (
        Diagnosis.INSUFFICIENT_DATA
    )
