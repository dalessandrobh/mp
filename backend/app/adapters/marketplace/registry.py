"""Escolhe o adapter conforme a configuração."""

from app.adapters.marketplace.base import MarketplaceAdapter
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import Settings


def get_marketplace_adapter(settings: Settings) -> MarketplaceAdapter:
    if settings.mock_marketplace:
        return MockAdapter()
    # Fase 9: ShopeeAdapter real.
    raise NotImplementedError("ShopeeAdapter ainda não implementado (Fase 9)")
