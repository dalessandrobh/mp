"""Consultas compartilhadas pelos serviços do funil."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ProductState
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState


def products_in_state(db: Session, state: ProductState) -> list[Product]:
    return list(
        db.execute(
            select(Product)
            .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
            .where(ProductCurrentState.state == state)
            .order_by(Product.id)
        ).scalars()
    )


def latest_snapshot(db: Session, product_id: int) -> ProductSnapshot | None:
    return db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id == product_id)
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()
