"""Receita esperada por clique (ev_v1), momento por Theil-Sen e a Beta.

O que estes testes travam, em uma frase: o ranking tem que responder "quanto rende?" e não
"é bonito?", o prior tem que ser prior (e ceder à evidência), e dado ausente nunca pode
virar zero nem reprovação.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import beta_dist, expected_value, momentum
from app.domain.expected_value import CvrPrior, EVInput

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------------ Beta


@pytest.mark.parametrize("q", [0.01, 0.1, 0.5, 0.9, 0.99])
@pytest.mark.parametrize("ab", [(1, 1), (4, 196), (0.5, 0.5), (50, 50), (2, 1000)])
def test_the_quantile_is_the_inverse_of_the_cdf(q, ab):
    a, b = ab
    x = beta_dist.quantile(q, a, b)
    assert beta_dist.cdf(x, a, b) == pytest.approx(q, abs=1e-9)


def test_the_uniform_case_is_the_identity():
    """Beta(1,1) é a uniforme: o quantil q vale q."""
    for q in (0.1, 0.25, 0.75):
        assert beta_dist.quantile(q, 1, 1) == pytest.approx(q, abs=1e-9)


def test_the_cdf_matches_a_closed_form_case():
    """Beta(2,1) tem CDF x². Confere a numérica contra a álgebra."""
    for x in (0.1, 0.4, 0.9):
        assert beta_dist.cdf(x, 2, 1) == pytest.approx(x * x, abs=1e-12)


def test_more_evidence_narrows_the_interval():
    """É isso que faz a decisão poder esperar pela amostra em vez de adivinhar."""
    def width(a, b):
        return beta_dist.quantile(0.9, a, b) - beta_dist.quantile(0.1, a, b)

    assert width(4, 196) > width(40, 1960) > width(400, 19600)


# ------------------------------------------------------------------ momento


def _series(values, *, hours=24):
    return [(NOW - timedelta(hours=hours * i), v) for i, v in enumerate(reversed(values))]


def test_a_rising_window_is_measured_as_acceleration():
    result = momentum.compute(_series([1000, 1100, 1200, 1300]))

    assert result is not None
    assert result.slope_per_day == Decimal("100.0000")
    assert result.relative == Decimal(str(round(100 / 1300, 6)))
    assert result.points == 4


def test_a_falling_window_gives_negative_momentum():
    """Medido na API real: `sales` é janela móvel e CAI. Queda é o sinal de saída."""
    result = momentum.compute(_series([2000, 1800, 1600]))

    assert result is not None and result.slope_per_day < 0
    assert result.relative < 0


def test_a_single_outlier_does_not_move_the_median_slope():
    """Theil-Sen e não mínimos quadrados: um reset de janela não vira tendência."""
    clean = momentum.compute(_series([1000, 1100, 1200, 1300, 1400]))
    spiked = momentum.compute(_series([1000, 1100, 9999, 1300, 1400]))

    assert clean is not None and spiked is not None
    assert abs(spiked.slope_per_day - clean.slope_per_day) < Decimal("30")


def test_an_irregular_series_uses_real_elapsed_time():
    """A descoberta não grava snapshot sem mudança: a série é irregular por construção."""
    points = [
        (NOW - timedelta(days=10), 1000),
        (NOW - timedelta(days=5), 1500),
        (NOW, 2000),
    ]
    result = momentum.compute(points)

    assert result is not None
    assert result.slope_per_day == Decimal("100.0000"), "500 em 5 dias = 100/dia"
    assert result.span_days == Decimal("10.000")


def test_too_few_points_or_too_short_a_span_is_not_zero_momentum():
    assert momentum.compute(_series([100, 200])) is None, "mediana de uma inclinação só"
    assert momentum.compute(_series([100, 200, 300], hours=2)) is None, "6 horas de série"
    assert momentum.compute([]) is None


def test_missing_sales_points_are_dropped_not_counted_as_zero():
    points = [
        (NOW - timedelta(days=3), 1000),
        (NOW - timedelta(days=2), None),
        (NOW - timedelta(days=1), 1100),
        (NOW, 1200),
    ]
    result = momentum.compute(points)

    assert result is not None and result.points == 3
    assert result.slope_per_day > 0


# ------------------------------------------------------------------ EV


def _ev(**overrides):
    base = dict(
        commission_value=Decimal("30.00"),
        price=Decimal("150.00"),
        sales_volume=1000,
        rating=Decimal("4.6"),
    )
    return expected_value.compute(EVInput(**{**base, **overrides}))


def test_ev_is_commission_times_the_conversion_estimate():
    result = _ev()

    assert result is not None
    expected = (result.commission_value * result.cvr_estimate).quantize(Decimal("0.000001"))
    assert result.ev_per_click == expected


def test_without_commission_there_is_no_ev():
    """Receita por clique não se estima sem saber quanto a venda paga."""
    assert _ev(commission_value=None) is None


def test_a_number_without_a_single_click_is_declared_as_prior():
    result = _ev()

    assert result is not None
    assert result.data_available is False, "prior vestido de número não é dado disponível"
    assert result.clicks == 0 and result.prior_source == "global"


def test_an_expensive_product_gets_a_lower_conversion_prior():
    """Regularidade empírica: conversão cai com o preço. Sem isso o topo de toda lista
    seria iPhone de R$ 9 mil, que paga muito por venda e converte pouco em rede social."""
    cheap = _ev(price=Decimal("50.00"), commission_value=Decimal("10.00"))
    pricey = _ev(price=Decimal("5000.00"), commission_value=Decimal("10.00"))

    assert cheap is not None and pricey is not None
    assert cheap.cvr_estimate > pricey.cvr_estimate


def test_proven_demand_and_acceleration_raise_the_prior():
    quiet = _ev(sales_volume=10, momentum=None)
    busy = _ev(sales_volume=20000, momentum=None)
    rising = _ev(sales_volume=20000, momentum=Decimal("0.3"))
    falling = _ev(sales_volume=20000, momentum=Decimal("-0.3"))

    assert busy.cvr_estimate > quiet.cvr_estimate
    assert rising.cvr_estimate > busy.cvr_estimate > falling.cvr_estimate


def test_missing_data_is_neutral_and_never_a_penalty():
    """Nenhum fator ausente pode rebaixar produto por falta de medição."""
    full = _ev(rating=Decimal("4.0"), sales_volume=1000, price=Decimal("100"))
    blind = _ev(rating=None, sales_volume=None, price=None)

    assert blind is not None and full is not None
    factors = blind.components["prior_factors"]
    assert {factors[k]["value"] for k in ("price", "demand", "rating", "momentum")} == {"1"}


def test_own_evidence_overrides_the_prior():
    """200 cliques equivalentes de prior: 2000 cliques próprios o tornam ruído de fundo."""
    prior_only = _ev()
    converting = _ev(clicks=2000, conversions=200)   # 10% medido
    not_converting = _ev(clicks=2000, conversions=2)  # 0,1% medido

    assert converting.cvr_estimate > prior_only.cvr_estimate > not_converting.cvr_estimate
    assert converting.cvr_estimate > Decimal("0.08")
    assert not_converting.cvr_estimate < Decimal("0.005")
    assert converting.data_available and not_converting.data_available


def test_one_sale_in_three_clicks_is_not_a_thirty_three_percent_converter():
    """A armadilha que o Bayes existe para evitar."""
    lucky = _ev(clicks=3, conversions=1)

    assert lucky is not None
    assert lucky.cvr_estimate < Decimal("0.04"), "a sorte não vira evidência"


def test_the_interval_brackets_the_estimate_and_narrows_with_evidence():
    thin = _ev(clicks=10, conversions=1)
    thick = _ev(clicks=5000, conversions=500)

    for result in (thin, thick):
        assert result.cvr_lower < result.cvr_estimate < result.cvr_upper
    assert (thick.cvr_upper - thick.cvr_lower) < (thin.cvr_upper - thin.cvr_lower)


def test_a_category_prior_replaces_the_global_one():
    result = _ev(
        category_prior=CvrPrior(mean=Decimal("0.05"), strength=Decimal("150"), source="categoria 1")
    )

    assert result is not None and result.prior_source == "categoria 1"
    assert result.components["prior_factors"]["base"]["value"] == "0.05"


def test_more_conversions_than_clicks_never_produces_a_rate_above_one():
    """Dado incoerente do relatório não pode virar CVR de 300%."""
    result = _ev(clicks=2, conversions=10)

    assert result is not None and result.conversions == 2
    assert result.cvr_estimate < Decimal("1")


def test_a_cheap_product_loses_to_an_expensive_one_only_when_the_money_justifies_it():
    """O ponto do ev_v1: R$ 1,76 por venda não compete com R$ 34, nem com CVR melhor."""
    cheap = _ev(commission_value=Decimal("1.76"), price=Decimal("22.00"), sales_volume=90000)
    good = _ev(commission_value=Decimal("34.00"), price=Decimal("136.00"), sales_volume=14000)

    assert cheap.cvr_estimate > good.cvr_estimate, "o barato converte melhor"
    assert good.ev_per_click > cheap.ev_per_click, "e ainda assim rende mais por clique"
