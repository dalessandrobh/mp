"""Veredito de risco de réplica para UM produto: o mesmo guarda em todo lugar.

O guarda (`domain/brand_risk`) é puro e só enxerga título, preço e categoria. Quem o aplica
precisa buscar o preço no último snapshot e passar o teto e as categorias de risco da
configuração; este módulo faz isso num só lugar, para a publicação, a fila de aprovação e a
entrada no portfólio não divergirem sobre o que é "suspeito".
"""

from collections.abc import Collection

from sqlalchemy.orm import Session

from app.domain import brand_risk
from app.models.catalog import Product
from app.services._funnel_queries import latest_snapshot


def assess_product(
    db: Session,
    product: Product,
    *,
    price_ceiling: float,
    brand_categories: Collection[str] = frozenset(),
) -> brand_risk.RiskVerdict:
    snapshot = latest_snapshot(db, product.id)
    price = float(snapshot.price) if snapshot is not None and snapshot.price is not None else None
    return brand_risk.assess(
        brand_risk.RiskInput(
            title=product.title,
            price=price,
            category_id=(product.category_path or [None])[0],
        ),
        price_ceiling=price_ceiling,
        brand_categories=frozenset(brand_categories),
    )
