"""Contrato dos marketplaces.

Adapters não conhecem o banco: devolvem dataclasses canônicas. Campo que a
API não informou vem como None — nunca como 0 (ver `formulas.py`).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import IntEnum


class SortBy(IntEnum):
    RELEVANCE = 1
    SALES = 2
    PRICE_DESC = 3
    PRICE_ASC = 4
    COMMISSION = 5


@dataclass(frozen=True)
class MarketplaceProduct:
    external_product_id: str
    title: str
    product_url: str
    offer_link: str | None = None
    image_url: str | None = None
    external_shop_id: str | None = None
    shop_name: str | None = None
    category_ids: tuple[str, ...] = ()
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    commission_rate: Decimal | None = None  # fração: 0.085 = 8,5%
    commission_value: Decimal | None = None
    rating: Decimal | None = None
    sales: int | None = None
    discount_rate: int | None = None  # percentual inteiro
    shop_types: tuple[int, ...] = ()  # 1=oficial, 2=preferred, 4=preferred+
    period_start: datetime | None = None
    period_end: datetime | None = None
    raw: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ProductPage:
    items: list[MarketplaceProduct]
    page: int
    has_next_page: bool


class MarketplaceAdapter(ABC):
    code: str
    display_name: str
    currency: str = "BRL"

    @abstractmethod
    def search_products(
        self,
        *,
        keyword: str | None = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        page: int = 1,
        limit: int = 20,
    ) -> ProductPage: ...

    @abstractmethod
    def get_product(self, external_product_id: str) -> MarketplaceProduct | None: ...
