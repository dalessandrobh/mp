"""Aritmética do teto de orçamento. Pura, para ser testável sem banco."""

from decimal import Decimal


def tier_caps(max_daily_ad_spend: Decimal, exploration_percentage: int) -> dict[str, Decimal]:
    exploration = (max_daily_ad_spend * exploration_percentage / 100).quantize(Decimal("0.01"))
    return {
        "GLOBAL": max_daily_ad_spend,
        "EXPLORATION": exploration,
        "EXPLOITATION": max_daily_ad_spend - exploration,
    }


def can_commit(cap: Decimal, used: Decimal, amount: Decimal) -> bool:
    """Valor positivo que cabe no que sobra do teto. Igualar o teto é permitido."""
    return amount > 0 and used + amount <= cap
