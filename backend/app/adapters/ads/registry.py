from app.adapters.ads.base import AdsAdapter
from app.adapters.ads.mock.adapter import MockAdsAdapter
from app.core.config import Settings


def get_ads_adapter(settings: Settings, *, token_store=None) -> AdsAdapter:
    if settings.mock_ads:
        return MockAdsAdapter()
    if settings.ads_provider == "pinterest":
        # Import tardio: o caminho de mock (testes, desenvolvimento) não carrega o cliente HTTP.
        from app.adapters.ads.pinterest.adapter import PinterestAdsAdapter
        from app.adapters.social.pinterest.factory import build_client

        return PinterestAdsAdapter(
            client=build_client(settings, token_store=token_store),
            ad_account_id=settings.pinterest_ad_account_id,
            country=settings.pinterest_ads_country,
        )
    raise NotImplementedError("MetaAdapter depende do UNKNOWN-7; use MOCK_ADS=true")
