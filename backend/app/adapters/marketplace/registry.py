from app.adapters.marketplace.base import MarketplaceAdapter
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import Settings


def get_marketplace_adapter(settings: Settings) -> MarketplaceAdapter:
    """Escolhe o adapter pelo modo de operação. Sem flag de mock, só Shopee (Fase 9)."""
    if settings.mock_marketplace:
        return MockAdapter()
    raise NotImplementedError("ShopeeAdapter entra na Fase 9; use MOCK_MARKETPLACE=true")
