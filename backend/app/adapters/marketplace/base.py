"""Contrato dos marketplaces.

Adapters não conhecem o banco: devolvem dataclasses canônicas e só. Todo campo
numérico é opcional porque a API de origem pode simplesmente não informá-lo —
e ausência nunca vira zero.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
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


@dataclass(frozen=True)
class AffiliateLink:
    short_url: str
    # Exatamente o que foi enviado como sub_id; é o que volta no relatório de conversões.
    sub_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConversionRecord:
    """Uma conversão do relatório do marketplace, já no formato canônico."""

    external_order_id: str
    # `utmContent` da Shopee. None = conversão não atribuível: nunca adivinhamos o dono.
    sub_id: str | None
    conversion_date: date
    commission_value: Decimal | None
    order_value: Decimal | None
    status: str
    fraud_status: str | None = None
    payload: dict | None = None


class MarketplaceAdapter(ABC):
    code: str
    display_name: str

    @abstractmethod
    def search_products(self, *, keyword: str | None = None, limit: int = 50) -> list[ProductOffer]:
        """Produtos em oferta. A paginação da API de origem fica escondida aqui."""

    @abstractmethod
    def generate_affiliate_link(
        self, *, origin_url: str, sub_ids: tuple[str, ...]
    ) -> AffiliateLink:
        """Link curto de afiliado carregando os sub_ids para atribuição."""

    @abstractmethod
    def fetch_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        """ConversionReport: comissão ESTIMADA, disponível em horas (PROVISIONAL).

        `hint_sub_ids` só serve aos mocks para gerar dado coerente; adapters reais
        ignoram, porque a API devolve tudo da conta.
        """

    @abstractmethod
    def fetch_validated_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        """ValidatedReport: comissão FINAL, 1-7 dias após o pedido (SETTLED)."""
