"""Marketplace fictício e determinístico (MOCK_MARKETPLACE=true).

O catálogo é gerado com semente fixa: duas execuções devolvem os mesmos
produtos, então testes e demonstrações são reproduzíveis. Parte dos produtos
sai propositalmente com dado faltando ou abaixo dos filtros, para exercitar
os caminhos de rejeição e de "dado ausente" do funil.
"""

import hashlib
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from app.adapters.marketplace.base import (
    AffiliateLink,
    ConversionRecord,
    MarketplaceAdapter,
    ProductOffer,
)

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

    def generate_affiliate_link(
        self, *, origin_url: str, sub_ids: tuple[str, ...]
    ) -> AffiliateLink:
        digest = hashlib.sha256("|".join((origin_url, *sub_ids)).encode()).hexdigest()[:10]
        return AffiliateLink(short_url=f"https://mock.example/s/{digest}", sub_ids=sub_ids)

    def fetch_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        return self._conversions(since, until, hint_sub_ids, validated=False)

    def fetch_validated_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        return self._conversions(since, until, hint_sub_ids, validated=True)

    @staticmethod
    def _conversions(
        since: date, until: date, sub_ids: Sequence[str], *, validated: bool
    ) -> list[ConversionRecord]:
        """Conversões determinísticas por (sub_id, dia).

        O ValidatedReport só traz pedidos COMPLETED e sem fraude, com a comissão
        final um pouco diferente da estimada — como na vida real. Ele também
        atrasa: pedidos dos últimos 2 dias ainda não liquidaram.
        """
        records: list[ConversionRecord] = []
        day = since
        while day <= until:
            if validated and day > date.today() - timedelta(days=2):
                day += timedelta(days=1)
                continue
            for sub_id in sub_ids:
                rng = random.Random(f"{sub_id}|{day.isoformat()}")
                for n in range(rng.choice((0, 0, 1, 1, 2))):
                    status = rng.choice(
                        ("COMPLETED", "COMPLETED", "COMPLETED", "PENDING", "CANCELLED")
                    )
                    fraud = "FRAUD" if rng.random() < 0.08 else "VERIFIED"
                    estimated = Decimal(rng.randint(300, 1500)) / 100
                    if validated and (status != "COMPLETED" or fraud == "FRAUD"):
                        continue
                    commission = (
                        (estimated * Decimal("0.93")).quantize(Decimal("0.01"))
                        if validated
                        else estimated
                    )
                    records.append(
                        ConversionRecord(
                            external_order_id=f"mock-ord-{sub_id[-14:]}-{day:%m%d}-{n}",
                            sub_id=sub_id,
                            conversion_date=day,
                            commission_value=commission,
                            order_value=(estimated * 12).quantize(Decimal("0.01")),
                            status=status,
                            fraud_status=fraud,
                            payload={"source": "mock", "validated": validated},
                        )
                    )
            day += timedelta(days=1)

        # Uma conversão sem sub_id por relatório: precisa ficar fora de qualquer produto.
        records.append(
            ConversionRecord(
                external_order_id=f"mock-orphan-{since:%Y%m%d}-{int(validated)}",
                sub_id=None,
                conversion_date=until,
                commission_value=Decimal("9.99"),
                order_value=Decimal("99.90"),
                status="COMPLETED",
                fraud_status="VERIFIED",
                payload={"source": "mock", "orphan": True},
            )
        )
        return records

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
