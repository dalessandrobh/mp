from decimal import Decimal

import pytest

from app.domain import formulas


class TestMissingDataIsNeverZero:
    """A regra mais importante do módulo: ausência de dado devolve None.

    Se virasse 0, o motor de decisão cortaria produto por falta de medição
    achando que ele teve desempenho ruim.
    """

    @pytest.mark.parametrize(
        "func,args",
        [
            (formulas.ctr, (None, 1000)),
            (formulas.ctr, (10, None)),
            (formulas.cpc, (None, 50)),
            (formulas.cvr, (5, None)),
            (formulas.epc, (None, 50)),
            (formulas.roas, (100, None)),
            (formulas.roi, (100, None)),
            (formulas.profit, (100, None)),
            (formulas.commission_value, (None, Decimal("0.08"))),
        ],
    )
    def test_missing_input_returns_none(self, func, args):
        assert func(*args) is None

    @pytest.mark.parametrize(
        "func,args",
        [
            (formulas.ctr, (10, 0)),
            (formulas.cpc, (Decimal("10"), 0)),
            (formulas.cvr, (1, 0)),
            (formulas.epc, (Decimal("10"), 0)),
            (formulas.roas, (Decimal("10"), 0)),
            (formulas.roi, (Decimal("10"), 0)),
        ],
    )
    def test_zero_denominator_returns_none(self, func, args):
        assert func(*args) is None


class TestValues:
    def test_ctr(self):
        assert formulas.ctr(50, 1000) == Decimal("0.05000")

    def test_cpc(self):
        assert formulas.cpc(Decimal("100.00"), 50) == Decimal("2.0000")

    def test_cvr(self):
        assert formulas.cvr(5, 50) == Decimal("0.10000")

    def test_epc(self):
        assert formulas.epc(Decimal("75.00"), 50) == Decimal("1.5000")

    def test_roas_breakeven_is_one(self):
        assert formulas.roas(Decimal("100"), Decimal("100")) == Decimal("1.0000")

    def test_roi_breakeven_is_zero(self):
        assert formulas.roi(Decimal("100"), Decimal("100")) == Decimal("0.0000")

    def test_roi_negative_when_spending_more_than_earning(self):
        assert formulas.roi(Decimal("50"), Decimal("100")) == Decimal("-0.5000")

    def test_profit(self):
        assert formulas.profit(Decimal("150.00"), Decimal("100.00")) == Decimal("50.00")

    def test_profit_can_be_negative(self):
        assert formulas.profit(Decimal("50.00"), Decimal("100.00")) == Decimal("-50.00")

    def test_commission_value(self):
        assert formulas.commission_value(Decimal("199.90"), Decimal("0.085")) == Decimal("16.99")


class TestSampleSufficiency:
    def test_sufficient_when_both_thresholds_met(self):
        assert formulas.is_sample_sufficient(
            60, 1500, min_clicks=50, min_impressions=1000
        )

    def test_insufficient_when_clicks_below_threshold(self):
        assert not formulas.is_sample_sufficient(
            10, 1500, min_clicks=50, min_impressions=1000
        )

    def test_missing_measurement_is_never_sufficient(self):
        assert not formulas.is_sample_sufficient(
            None, 1500, min_clicks=50, min_impressions=1000
        )
