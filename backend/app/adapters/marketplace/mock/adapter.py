"""Marketplace fictício e determinístico (MOCK_MARKETPLACE=true).

Mesma seed, mesmo catálogo. Alguns produtos nascem com campos ausentes de
propósito, para os testes exercitarem o caminho "dado indisponível".
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.adapters.marketplace.base import (
    MarketplaceAdapter,
    MarketplaceProduct,
    ProductPage,
    SortBy,
)

_NOUNS = [
    "Fone Bluetooth",
    "Garrafa Térmica",
    "Mochila",
    "Luminária LED",
    "Teclado Gamer",
    "Camiseta Dry Fit",
    "Tênis Casual",
    "Organizador",
    "Mini Liquidificador",
    "Relógio",
]
_ADJ = ["Pro", "Slim", "Compacto", "Premium", "Básico", "Max"]


def _build_catalog(size: int, seed: int, now: datetime) -> list[MarketplaceProduct]:
    rng = random.Random(seed)
    catalog = []
    for i in range(size):
        price = Decimal(rng.randint(1500, 30000)) / 100
        rate = Decimal(rng.randint(10, 150)) / 1000
        shop_pool = [(1,), (2,), (4,), (1, 4), ()]
        item_id = str(10_000 + i)
        # ~1 em cada 8 produtos perde vendas e rating (a API nem sempre devolve).
        sparse = i % 8 == 7
        # ~1 em cada 10 já expirou.
        expired = i % 10 == 9
        catalog.append(
            MarketplaceProduct(
                external_product_id=item_id,
                title=f"{rng.choice(_NOUNS)} {rng.choice(_ADJ)} #{i}",
                product_url=f"https://mock.shop/product/{item_id}",
                offer_link=f"https://mock.shop/o/{item_id}",
                image_url=f"https://mock.shop/img/{item_id}.jpg",
                external_shop_id=str(900 + i % 7),
                shop_name=f"Loja {i % 7}",
                category_ids=("100001", str(100100 + i % 5)),
                price_min=price,
                price_max=price + Decimal(rng.randint(0, 2000)) / 100,
                commission_rate=rate,
                commission_value=(price * rate).quantize(Decimal("0.01")),
                rating=None if sparse else Decimal(rng.randint(30, 50)) / 10,
                sales=None if sparse else rng.choice([0, 3, 12, 40, 150, 800, 4200]),
                discount_rate=rng.choice([0, 5, 10, 25, 40]),
                shop_types=rng.choice(shop_pool),
                period_start=now - timedelta(days=30),
                period_end=now - timedelta(days=1)
                if expired
                else now + timedelta(days=rng.randint(3, 90)),
                raw={"mock": True, "index": i},
            )
        )
    return catalog


class MockAdapter(MarketplaceAdapter):
    code = "mock"
    display_name = "Mock Marketplace"

    def __init__(self, *, size: int = 40, seed: int = 42, now: datetime | None = None):
        self._catalog = _build_catalog(size, seed, now or datetime.now(UTC))

    def search_products(
        self,
        *,
        keyword: str | None = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        page: int = 1,
        limit: int = 20,
    ) -> ProductPage:
        items = self._catalog
        if keyword:
            needle = keyword.lower()
            items = [p for p in items if needle in p.title.lower()]

        if sort_by is SortBy.SALES:
            items = sorted(
                items, key=lambda p: p.sales if p.sales is not None else -1, reverse=True
            )
        elif sort_by is SortBy.COMMISSION:
            items = sorted(items, key=lambda p: p.commission_rate or Decimal(0), reverse=True)
        elif sort_by is SortBy.PRICE_DESC:
            items = sorted(items, key=lambda p: p.price_min or Decimal(0), reverse=True)
        elif sort_by is SortBy.PRICE_ASC:
            items = sorted(items, key=lambda p: p.price_min or Decimal(0))

        start = (max(page, 1) - 1) * limit
        window = items[start : start + limit]
        return ProductPage(items=window, page=page, has_next_page=start + limit < len(items))

    def get_product(self, external_product_id: str) -> MarketplaceProduct | None:
        return next(
            (p for p in self._catalog if p.external_product_id == external_product_id), None
        )
