from decimal import Decimal

from app.domain import performance_score
from app.domain.performance_score import PerformanceInput

D = Decimal


def _input(**overrides) -> PerformanceInput:
    base = dict(
        roi=D("1.0"), ctr=D("0.02"), cvr=D("0.04"), daily_rois=(D("1.0"), D("1.0"), D("1.0"))
    )
    return PerformanceInput(**{**base, **overrides})


def test_perfect_product_scores_100():
    result = performance_score.compute(_input())

    assert result.score == D("100.000")
    assert result.data_available is True


def test_break_even_roi_is_the_midpoint():
    result = performance_score.compute(_input(roi=D("0"), ctr=None, cvr=None, daily_rois=()))

    assert result.components["roi"]["value"] == "50.000"


def test_missing_components_are_dropped_not_zeroed():
    full = performance_score.compute(_input())
    partial = performance_score.compute(_input(cvr=None))

    assert partial.score == full.score
    assert partial.data_available is False
    assert partial.missing_fields == ("cvr",)


def test_stability_needs_enough_days():
    short = performance_score.compute(_input(daily_rois=(D("1.0"), D("-1.0"))))

    assert short.components["stability"]["available"] is False


def test_erratic_roi_lowers_stability():
    steady = performance_score.compute(_input(daily_rois=(D("0.5"),) * 4))
    erratic = performance_score.compute(_input(daily_rois=(D("2"), D("-1"), D("2"), D("-1"))))

    assert erratic.score < steady.score


def test_no_data_returns_none():
    assert performance_score.compute(PerformanceInput(None, None, None, ())) is None
