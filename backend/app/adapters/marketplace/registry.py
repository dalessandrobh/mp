from app.adapters.marketplace.base import MarketplaceAdapter
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import Settings


def get_marketplace_adapter(settings: Settings) -> MarketplaceAdapter:
    """Escolhe o adapter pelo modo de operação (MOCK_MARKETPLACE)."""
    if settings.mock_marketplace:
        return MockAdapter()
    # Import tardio: o modo mock não carrega nem valida nada da Shopee.
    from app.adapters.marketplace.shopee.adapter import ShopeeAdapter

    return ShopeeAdapter.from_settings(settings)
