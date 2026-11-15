from decimal import Decimal

from app.domain import content_fit


def test_preferred_category_beats_discouraged_one_at_the_same_price():
    assert content_fit.penalty("Casa e Utilidades", 80) < content_fit.penalty(
        "Celulares e Acessórios", 80
    )


def test_cheaper_is_better_inside_the_same_category():
    low, mid, high = (content_fit.penalty("Beleza", p) for p in (60, 150, 280))
    assert low < mid < high


def test_unknown_category_and_price_are_neutral_not_penalised_to_the_bottom():
    assert content_fit.category_penalty(None) == 1
    assert content_fit.category_penalty("Categoria Nova") == 1
    assert content_fit.price_penalty(None) == 1


def test_category_match_ignores_case_and_accents():
    assert content_fit.category_penalty("CASA E UTILIDADES") == 0
    assert content_fit.category_penalty("roupas femininas e lingerie") == 0


def test_price_band_edges():
    assert content_fit.price_penalty(Decimal("100")) == 0
    assert content_fit.price_penalty(Decimal("100.01")) == 1
    assert content_fit.price_penalty(Decimal("200")) == 1
    assert content_fit.price_penalty(Decimal("200.01")) == 2
