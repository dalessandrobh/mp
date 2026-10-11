"""Discovery: traz produtos do marketplace e os coloca no funil.

Idempotente: rodar duas vezes não duplica produto nem estado. O snapshot é
append-only, então cada execução registra o preço/comissão daquele momento.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter, MarketplaceProduct, SortBy
from app.domain import state_machine
from app.domain.enums import ProductState
from app.models.catalog import Marketplace, Product, ProductSnapshot

ACTOR = "system"


@dataclass(frozen=True)
class DiscoveryResult:
    seen: int
    new_products: int
    snapshots: int


def get_or_create_marketplace(db: Session, adapter: MarketplaceAdapter) -> Marketplace:
    record = db.execute(
        select(Marketplace).where(Marketplace.code == adapter.code)
    ).scalar_one_or_none()
    if record is None:
        record = Marketplace(
            code=adapter.code,
            display_name=adapter.display_name,
            currency=adapter.currency,
            adapter_class=f"{type(adapter).__module__}.{type(adapter).__name__}",
        )
        db.add(record)
        db.flush()
    return record


def _snapshot_from(product_id: int, p: MarketplaceProduct) -> ProductSnapshot:
    availability = {
        "price": p.price_min is not None,
        "commission_rate": p.commission_rate is not None,
        "commission_value": p.commission_value is not None,
        "rating": p.rating is not None,
        "sales_volume": p.sales is not None,
        "stock": False,  # a API de afiliados não expõe estoque
    }
    return ProductSnapshot(
        product_id=product_id,
        price=p.price_min,
        original_price=None,
        commission_rate=p.commission_rate,
        commission_value=p.commission_value,
        rating=p.rating,
        rating_count=None,
        sales_volume=p.sales,
        stock=None,
        data_available=availability,
        raw_payload={
            "price_max": str(p.price_max) if p.price_max is not None else None,
            "discount_rate": p.discount_rate,
            "shop_types": list(p.shop_types),
            "period_start": p.period_start.isoformat() if p.period_start else None,
            "period_end": p.period_end.isoformat() if p.period_end else None,
            "offer_link": p.offer_link,
        },
    )


def run_discovery(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    keyword: str | None = None,
    sort_by: SortBy = SortBy.COMMISSION,
    pages: int = 1,
    limit: int = 20,
) -> DiscoveryResult:
    marketplace = get_or_create_marketplace(db, adapter)
    now = datetime.now(UTC)
    seen = new = snaps = 0

    for page_no in range(1, pages + 1):
        page = adapter.search_products(keyword=keyword, sort_by=sort_by, page=page_no, limit=limit)
        for item in page.items:
            seen += 1
            product = db.execute(
                select(Product).where(
                    Product.marketplace_id == marketplace.id,
                    Product.external_product_id == item.external_product_id,
                )
            ).scalar_one_or_none()

            if product is None:
                product = Product(
                    marketplace_id=marketplace.id,
                    external_product_id=item.external_product_id,
                    external_shop_id=item.external_shop_id,
                    title=item.title,
                    category_path=list(item.category_ids) or None,
                    product_url=item.product_url,
                    image_url=item.image_url,
                    raw_payload=item.raw,
                )
                db.add(product)
                db.flush()
                new += 1
                state_machine.transition(
                    db,
                    product_id=product.id,
                    to_state=ProductState.DISCOVERY,
                    reason_code="discovered",
                    actor=ACTOR,
                    reason_detail=f"keyword={keyword!r} sort={sort_by.name}",
                )
            else:
                product.last_seen_at = now

            db.add(_snapshot_from(product.id, item))
            snaps += 1

        if not page.has_next_page:
            break

    db.flush()
    return DiscoveryResult(seen=seen, new_products=new, snapshots=snaps)
