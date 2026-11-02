"""Descoberta: traz ofertas do marketplace e as registra no funil.

Produto novo entra em DISCOVERY pela state machine. Produto conhecido ganha
só um novo snapshot — preço e comissão mudam, e a decisão de ontem precisa do
valor de ontem.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter, ProductOffer
from app.domain import formulas
from app.domain.enums import ProductState
from app.domain.state_machine import transition
from app.models.catalog import Marketplace, Product, ProductSnapshot

ACTOR = "system"


@dataclass(frozen=True)
class DiscoveryResult:
    fetched: int
    new_products: int
    updated_products: int


def ensure_marketplace(db: Session, adapter: MarketplaceAdapter) -> Marketplace:
    record = db.execute(
        select(Marketplace).where(Marketplace.code == adapter.code)
    ).scalar_one_or_none()
    unsupported = sorted(adapter.unsupported_fields)
    if record is None:
        record = Marketplace(
            code=adapter.code,
            display_name=adapter.display_name,
            adapter_class=f"{type(adapter).__module__}.{type(adapter).__name__}",
            config={"unsupported_fields": unsupported},
        )
        db.add(record)
        db.flush()
    elif (record.config or {}).get("unsupported_fields") != unsupported:
        # Reatribui o dict inteiro: o JSONB não detecta mutação in-place.
        record.config = {**(record.config or {}), "unsupported_fields": unsupported}
        db.flush()
    return record


def _snapshot_from(product_id: int, offer: ProductOffer) -> ProductSnapshot:
    return ProductSnapshot(
        product_id=product_id,
        price=offer.price,
        original_price=offer.original_price,
        commission_rate=offer.commission_rate,
        commission_value=formulas.commission_value(offer.price, offer.commission_rate),
        rating=offer.rating,
        rating_count=offer.rating_count,
        sales_volume=offer.sales_volume,
        stock=offer.stock,
        data_available=offer.data_available(),
        raw_payload=offer.raw_payload,
    )


def run_discovery(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    keyword: str | None = None,
    limit: int = 50,
) -> DiscoveryResult:
    marketplace = ensure_marketplace(db, adapter)
    offers = adapter.search_products(keyword=keyword, limit=limit)
    now = datetime.now(UTC)
    new_count = updated_count = 0

    for offer in offers:
        product = db.execute(
            select(Product).where(
                Product.marketplace_id == marketplace.id,
                Product.external_product_id == offer.external_product_id,
            )
        ).scalar_one_or_none()

        if product is None:
            product = Product(
                marketplace_id=marketplace.id,
                external_product_id=offer.external_product_id,
                external_shop_id=offer.external_shop_id,
                title=offer.title,
                category_path=list(offer.category_path) if offer.category_path else None,
                product_url=offer.product_url,
                image_url=offer.image_url,
                raw_payload=offer.raw_payload,
            )
            db.add(product)
            db.flush()
            transition(
                db,
                product_id=product.id,
                to_state=ProductState.DISCOVERY,
                reason_code="DISCOVERED",
                actor=ACTOR,
            )
            new_count += 1
        else:
            product.title = offer.title
            product.product_url = offer.product_url
            product.image_url = offer.image_url
            product.last_seen_at = now
            updated_count += 1

        db.add(_snapshot_from(product.id, offer))

    db.flush()
    return DiscoveryResult(
        fetched=len(offers), new_products=new_count, updated_products=updated_count
    )
