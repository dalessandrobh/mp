"""Cota por categoria: nenhuma categoria nível 1 pode dominar o portfólio.

Sem isto, a categoria com mais produtos bem pontuados ocuparia todas as vagas e o teste
deixaria de comparar categorias entre si. Produto sem categoria conhecida não é limitado:
desconhecido não é uma categoria.
"""

import math
from collections import Counter

from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.services import portfolio_service


def first_category(product: Product) -> str | None:
    path = product.category_path or []
    return str(path[0]) if path else None


def cap_per_category(max_active_products: int, share_pct: int) -> int:
    """Máximo de produtos por categoria. Nunca menos que 1 (senão ninguém entra)."""
    return max(1, math.ceil(max_active_products * share_pct / 100))


def portfolio_counts(db: Session, *, exclude: set[int] | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in portfolio_service.active_entries(db):
        if exclude and entry.product_id in exclude:
            continue
        product = db.get(Product, entry.product_id)
        category = first_category(product) if product else None
        if category:
            counts[category] += 1
    return counts


def full_categories(counts: Counter[str], cap: int) -> frozenset[str]:
    return frozenset(c for c, n in counts.items() if n >= cap)
