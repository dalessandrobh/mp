from app.adapters.ads.base import AdsAdapter
from app.adapters.ads.mock.adapter import MockAdsAdapter
from app.core.config import Settings


def get_ads_adapter(settings: Settings) -> AdsAdapter:
    if settings.mock_ads:
        return MockAdsAdapter()
    raise NotImplementedError("MetaAdapter depende do UNKNOWN-7; use MOCK_ADS=true")
