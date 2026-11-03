from app.domain import brand_risk
from app.domain.brand_risk import RiskInput


def _assess(title, price, category=None, ceiling=800.0, cats=frozenset()):
    return brand_risk.assess(
        RiskInput(title=title, price=price, category_id=category),
        price_ceiling=ceiling,
        brand_categories=cats,
    )


def test_cheap_product_passes_even_with_a_brand_in_the_title():
    verdict = _assess("Capinha para iPhone 15", 39.90)
    assert verdict.blocked is False


def test_high_ticket_with_a_brand_is_blocked():
    verdict = _assess("Celular iPhone 17 Pro Max 256GB Lacrado", 9149.00)
    assert verdict.blocked is True
    assert verdict.reason_code == "RISK_HIGH_TICKET_BRAND"
    assert "iphone" in verdict.why


def test_high_ticket_in_a_brand_category_is_blocked_without_a_brand_word():
    verdict = _assess("Smartphone genérico 256GB", 3200.00, category="100013",
                      cats=frozenset({"100013"}))
    assert verdict.blocked is True
    assert verdict.reason_code == "RISK_HIGH_TICKET_CATEGORY"


def test_high_ticket_without_brand_or_risky_category_passes():
    # Bicicleta de R$ 3.199 é o caso que o guarda NÃO deve barrar: comissão alta,
    # sem marca de eletrônico, categoria fora da lista.
    verdict = _assess("Bicicleta Elétrica Aro 29 Aluminio", 3199.00, category="100637")
    assert verdict.blocked is False


def test_missing_price_blocks_because_risk_cannot_be_judged():
    verdict = _assess("Qualquer coisa", None)
    assert verdict.blocked is True
    assert verdict.reason_code == "RISK_UNKNOWN_PRICE"


def test_brand_matching_is_whole_word_so_everyday_words_do_not_trip_it():
    # 'lg' dentro de 'algodão' e 'amd' dentro de 'amendoim' derrubariam uma busca
    # por substring, e aí o guarda barraria toalha e doce de R$ 1.000.
    assert brand_risk.brands_in("Toalha de algodão egípcio premium") == ()
    assert brand_risk.brands_in("Caixa de amendoim doce 5kg") == ()
    assert brand_risk.brands_in("Smart TV LG 55 polegadas") == ("lg",)


def test_accents_and_case_do_not_hide_a_brand():
    assert brand_risk.brands_in("SAMSUNG Galaxy S30") == ("galaxy", "samsung")
