"""A app não sobe com configuração incoerente — falha na subida, não em produção."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def build(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_are_safe():
    settings = build()

    # O default nunca toca sistema externo nem gasta dinheiro.
    assert settings.mock_marketplace
    assert settings.mock_ads
    assert settings.dry_run
    assert settings.ai_autonomy_level == 1
    assert not settings.opportunity_use_llm


def test_budget_split_must_total_100():
    with pytest.raises(ValidationError):
        build(exploration_percentage=30, exploitation_percentage=60)


def test_min_products_cannot_exceed_max():
    with pytest.raises(ValidationError):
        build(min_active_products=20, max_active_products=10)


def test_test_budget_cannot_exceed_global_cap():
    with pytest.raises(ValidationError):
        build(max_daily_ad_spend="50.00", min_daily_test_budget="80.00")


def test_autonomy_level_is_bounded():
    with pytest.raises(ValidationError):
        build(ai_autonomy_level=6)


def test_production_rejects_placeholder_secrets():
    with pytest.raises(ValidationError):
        build(app_env="production")


def test_llm_enabled_requires_a_provider():
    with pytest.raises(ValidationError):
        build(opportunity_use_llm=True, llm_provider="null")


def test_real_marketplace_requires_credentials():
    with pytest.raises(ValidationError):
        build(mock_marketplace=False)


def test_real_ads_requires_credentials():
    with pytest.raises(ValidationError):
        build(mock_ads=False)
