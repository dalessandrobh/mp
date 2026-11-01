"""Contrato dos marketplaces.

Adapters não conhecem o banco: devolvem dataclasses canônicas e só. Todo campo
numérico é opcional porque a API de origem pode simplesmente não informá-lo —
e ausência nunca vira zero.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProductOffer:
    external_product_id: str
    title: str
    product_url: str
    external_shop_id: str | None = None
    category_path: tuple[str, ...] | None = None
    image_url: str | None = None
    price: Decimal | None = None
    original_price: Decimal | None = None
    # Fração: 0.085 = 8,5%.
    commission_rate: Decimal | None = None
    rating: Decimal | None = None
    rating_count: int | None = None
    sales_volume: int | None = None
    stock: int | None = None
    raw_payload: dict | None = None

    def data_available(self) -> dict[str, bool]:
        """Mapa campo -> veio da API? Alimenta `product_snapshots.data_available`."""
        return {
            name: getattr(self, name) is not None
            for name in (
                "price",
                "original_price",
                "commission_rate",
                "rating",
                "rating_count",
                "sales_volume",
                "stock",
            )
        }


class MarketplaceAdapter(ABC):
    code: str
    display_name: str

    @abstractmethod
    def search_products(self, *, keyword: str | None = None, limit: int = 50) -> list[ProductOffer]:
        """Produtos em oferta. A paginação da API de origem fica escondida aqui."""
