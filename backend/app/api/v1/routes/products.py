"""Produtos do funil: a lista e o detalhe que o dashboard mostra (PLANNING §5.2).

Só leitura. Tudo aqui é o que o motor ENXERGA: o último snapshot, o último score e o motivo
da última mudança de estado. Campo que a API do marketplace não informou sai como null —
nunca como zero.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, NotFound
from app.core.security import require_reader
from app.db.session import get_db
from app.domain.enums import ProductState
from app.models.catalog import Category, Marketplace, Product, ProductSnapshot
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.scoring import OpportunityScore
from app.models.tracking import AffiliateLink

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_reader)])

SORTS = ("score", "recent", "commission", "sales")


def _num(value) -> str | None:
    return None if value is None else str(value)


def _category(path: list[str] | None, marketplace: str | None, names: dict) -> dict | None:
    """Categoria de nível 1: {id, name}. Sem nome cadastrado, o ID (ou o texto, no mock)."""
    if not path:
        return None
    raw = path[0]
    name = names.get((marketplace, raw))
    if name is None:
        name = f"Categoria {raw}" if raw.isdigit() else raw
    return {"id": raw, "name": name}


def _names(db: Session) -> dict:
    return {
        (c.marketplace, c.external_id): c.name
        for c in db.execute(select(Category).where(Category.level == 1)).scalars()
    }


def _snapshot_dict(s: ProductSnapshot | None) -> dict | None:
    if s is None:
        return None
    return {
        "captured_at": s.captured_at,
        "price": _num(s.price),
        "commission_rate": _num(s.commission_rate),
        "commission_value": _num(s.commission_value),
        "rating": _num(s.rating),
        "rating_count": s.rating_count,
        "sales_volume": s.sales_volume,
        "stock": s.stock,
        "data_available": s.data_available,
    }


def _score_dict(s: OpportunityScore | None, *, full: bool = False) -> dict | None:
    if s is None:
        return None
    body = {
        "score": _num(s.score),
        "data_available": s.data_available,
        "missing_fields": list(s.missing_fields or []),
        "algorithm_version": s.algorithm_version,
        "computed_at": s.computed_at,
    }
    if full:
        body["components"] = s.components
    return body


@router.get("")
def list_products(
    state: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    min_score: float | None = Query(default=None, ge=0, le=100),
    category: str | None = Query(default=None, max_length=40),
    sort: str = "score",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    if sort not in SORTS:
        raise DomainError(f"sort inválido: {sort}", details={"allowed": list(SORTS)})
    wanted_state = None
    if state:
        try:
            wanted_state = ProductState(state)
        except ValueError as exc:
            raise DomainError(f"state inválido: {state}") from exc

    latest_snapshot = (
        select(func.max(ProductSnapshot.id).label("id"), ProductSnapshot.product_id)
        .group_by(ProductSnapshot.product_id)
        .subquery()
    )
    latest_score = (
        select(func.max(OpportunityScore.id).label("id"), OpportunityScore.product_id)
        .group_by(OpportunityScore.product_id)
        .subquery()
    )

    base = (
        select(Product, ProductCurrentState, Marketplace.code, ProductSnapshot, OpportunityScore,
               ProductStateTransition)
        .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .join(Marketplace, Marketplace.id == Product.marketplace_id)
        .outerjoin(latest_snapshot, latest_snapshot.c.product_id == Product.id)
        .outerjoin(ProductSnapshot, ProductSnapshot.id == latest_snapshot.c.id)
        .outerjoin(latest_score, latest_score.c.product_id == Product.id)
        .outerjoin(OpportunityScore, OpportunityScore.id == latest_score.c.id)
        .outerjoin(
            ProductStateTransition,
            ProductStateTransition.id == ProductCurrentState.last_transition,
        )
    )
    if q:
        base = base.where(Product.title.ilike(f"%{q.strip()}%"))

    # Contagem por estado respeita a busca, mas NÃO o filtro de estado: são os chips do topo.
    counts = dict(
        db.execute(
            select(ProductCurrentState.state, func.count())
            .join(Product, Product.id == ProductCurrentState.product_id)
            .where(*([Product.title.ilike(f"%{q.strip()}%")] if q else []))
            .group_by(ProductCurrentState.state)
        ).all()
    )

    if category:
        base = base.where(Product.category_path[1] == category)
    if wanted_state is not None:
        base = base.where(ProductCurrentState.state == wanted_state)
    if min_score is not None:
        base = base.where(OpportunityScore.score >= min_score)

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    order = {
        "score": [OpportunityScore.score.desc().nulls_last()],
        "recent": [ProductCurrentState.since.desc()],
        "commission": [ProductSnapshot.commission_value.desc().nulls_last()],
        "sales": [ProductSnapshot.sales_volume.desc().nulls_last()],
    }[sort]
    rows = db.execute(base.order_by(*order, Product.id).limit(limit).offset(offset)).all()

    names = _names(db)
    first_category = Product.category_path[1].label("first_category")
    by_category = db.execute(
        select(Marketplace.code, first_category, func.count())
        .join(Marketplace, Marketplace.id == Product.marketplace_id)
        .where(
            Product.category_path.is_not(None),
            *([Product.title.ilike(f"%{q.strip()}%")] if q else []),
        )
        .group_by(Marketplace.code, first_category)
    ).all()
    categories = sorted(
        (
            {**_category([raw], code, names), "count": n}  # type: ignore[dict-item]
            for code, raw, n in by_category
            if raw
        ),
        key=lambda c: (-c["count"], c["name"]),
    )

    return {
        "total": total,
        "counts": {s.value: n for s, n in counts.items()},
        "categories": categories,
        "items": [
            {
                "id": product.id,
                "title": product.title,
                "product_url": product.product_url,
                "image_url": product.image_url,
                "marketplace": marketplace,
                "category": _category(product.category_path, marketplace, names),
                "state": current.state.value,
                "state_since": current.since,
                "last_reason_code": transition.reason_code if transition else None,
                "last_actor": transition.actor if transition else None,
                "snapshot": _snapshot_dict(snapshot),
                "opportunity": _score_dict(score),
            }
            for product, current, marketplace, snapshot, score, transition in rows
        ],
    }


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound(f"produto {product_id} não existe")

    current = db.get(ProductCurrentState, product_id)
    marketplace = db.get(Marketplace, product.marketplace_id)
    transitions = db.execute(
        select(ProductStateTransition)
        .where(ProductStateTransition.product_id == product_id)
        .order_by(ProductStateTransition.id.desc())
        .limit(50)
    ).scalars()
    snapshots = db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id == product_id)
        .order_by(ProductSnapshot.id.desc())
        .limit(30)
    ).scalars()
    scores = db.execute(
        select(OpportunityScore)
        .where(OpportunityScore.product_id == product_id)
        .order_by(OpportunityScore.id.desc())
        .limit(10)
    ).scalars()
    links = db.execute(
        select(AffiliateLink)
        .where(AffiliateLink.product_id == product_id, AffiliateLink.revoked_at.is_(None))
        .order_by(AffiliateLink.id.desc())
        .limit(5)
    ).scalars()

    return {
        "id": product.id,
        "title": product.title,
        "product_url": product.product_url,
        "image_url": product.image_url,
        "marketplace": marketplace.code if marketplace else None,
        "category_path": product.category_path,
        "category": _category(
            product.category_path, marketplace.code if marketplace else None, _names(db)
        ),
        "first_seen_at": product.first_seen_at,
        "last_seen_at": product.last_seen_at,
        "state": current.state.value if current else None,
        "state_since": current.since if current else None,
        "history": [
            {
                "from_state": t.from_state.value if t.from_state else None,
                "to_state": t.to_state.value,
                "reason_code": t.reason_code,
                "reason_detail": t.reason_detail,
                "actor": t.actor,
                "metrics_used": t.metrics_used,
                "created_at": t.created_at,
            }
            for t in transitions
        ],
        "snapshots": [_snapshot_dict(s) for s in snapshots],
        "scores": [_score_dict(s, full=True) for s in scores],
        "links": [
            {"sub_id": link.sub_id, "short_url": link.short_url, "channel": link.channel}
            for link in links
        ],
    }
