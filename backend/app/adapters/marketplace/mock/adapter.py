"""Marketplace fictício e determinístico (MOCK_MARKETPLACE=true).

O catálogo é gerado com semente fixa: duas execuções devolvem os mesmos
produtos, então testes e demonstrações são reproduzíveis. Parte dos produtos
sai propositalmente com dado faltando ou abaixo dos filtros, para exercitar
os caminhos de rejeição e de "dado ausente" do funil.
"""

import random
from decimal import Decimal

from app.adapters.marketplace.base import MarketplaceAdapter, ProductOffer

_CATALOG_SIZE = 40
_SEED = 42

_CATEGORIES = (
    ("Casa", "Cozinha"),
    ("Eletrônicos", "Acessórios"),
    ("Beleza", "Cuidados com a pele"),
    ("Esporte", "Fitness"),
    ("Moda", "Acessórios"),
)


class MockAdapter(MarketplaceAdapter):
    code = "mock"
    display_name = "Mock Marketplace"

    def __init__(self) -> None:
        self._catalog = self._build_catalog()

    def search_products(self, *, keyword: str | None = None, limit: int = 50) -> list[ProductOffer]:
        offers = self._catalog
        if keyword:
            needle = keyword.lower()
            offers = [o for o in offers if needle in o.title.lower()]
        return offers[:limit]

    @staticmethod
    def _build_catalog() -> list[ProductOffer]:
        rng = random.Random(_SEED)
        offers: list[ProductOffer] = []

        for index in range(_CATALOG_SIZE):
            category = _CATEGORIES[index % len(_CATEGORIES)]
            price = Decimal(rng.randint(1500, 45000)) / 100

            # Os últimos produtos de cada bloco de 10 simulam falhas conhecidas.
            quirk = index % 10
            rating = Decimal(str(round(rng.uniform(3.2, 5.0), 2)))
            rating_count: int | None = rng.randint(2, 900)
            sales_volume: int | None = rng.randint(0, 6000)
            stock: int | None = rng.randint(1, 300)
            commission_rate: Decimal | None = Decimal(str(round(rng.uniform(0.01, 0.14), 4)))

            if quirk == 7:
                sales_volume = None  # API não informou vendas
            if quirk == 8:
                stock = 0
            if quirk == 9:
                commission_rate = None  # sem comissão não há como qualificar

            offers.append(
                ProductOffer(
                    external_product_id=f"mock-{index + 1:04d}",
                    external_shop_id=f"shop-{index % 6 + 1}",
                    title=f"Produto {category[1]} {index + 1}",
                    category_path=category,
                    product_url=f"https://mock.example/p/{index + 1}",
                    image_url=f"https://mock.example/img/{index + 1}.jpg",
                    price=price,
                    original_price=(price * Decimal("1.2")).quantize(Decimal("0.01")),
                    commission_rate=commission_rate,
                    rating=rating,
                    rating_count=rating_count,
                    sales_volume=sales_volume,
                    stock=stock,
                    raw_payload={"source": "mock", "index": index},
                )
            )
        return offers
