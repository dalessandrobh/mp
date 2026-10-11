"""Qualification: filtra o que entrou no funil e calcula o Opportunity Score.

Regra central: ausência de dado nunca reprova. Produto sem comissão ou sem
vendas fica em QUALIFICATION aguardando dado; só números ruins rejeitam.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceProduct
from app.domain import state_machine
from app.domain.enums import ProductState
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState
from app.models.scoring import OpportunityScore
from app.services.opportunity_scoring import ScoreResult, compute_opportunity_score

ACTOR = "system"

MIN_COMMISSION_RATE = Decimal("0.03")
MIN_RATING = Decimal("4.0")
MIN_SALES = 10


@dataclass(frozen=True)
class QualificationResult:
    evaluated: int = 0
    candidates: list[int] = field(default_factory=list)
    rejected: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    waiting_data: list[int] = field(default_factory=list)


def _latest_snapshot(db: Session, product_id: int) -> ProductSnapshot | None:
    return db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id == product_id)
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _to_marketplace_product(product: Product, snap: ProductSnapshot) -> MarketplaceProduct:
    extra = snap.raw_payload or {}
    return MarketplaceProduct(
        external_product_id=product.external_product_id,
        title=product.title,
        product_url=product.product_url,
        price_min=snap.price,
        commission_rate=snap.commission_rate,
        commission_value=snap.commission_value,
        rating=snap.rating,
        sales=snap.sales_volume,
        discount_rate=extra.get("discount_rate"),
        shop_types=tuple(extra.get("shop_types") or ()),
        period_start=_parse_dt(extra.get("period_start")),
        period_end=_parse_dt(extra.get("period_end")),
    )


def _verdict(p: MarketplaceProduct, now: datetime) -> tuple[ProductState | None, str]:
    """(estado destino, reason_code). Destino None = aguardar dado."""
    if p.period_end is not None and p.period_end <= now:
        return ProductState.EXPIRED, "offer_expired"
    if p.commission_rate is None or p.sales is None:
        return None, "awaiting_data"
    if p.commission_rate < MIN_COMMISSION_RATE:
        return ProductState.REJECTED, "low_commission"
    if p.sales < MIN_SALES:
        return ProductState.REJECTED, "low_sales"
    if p.rating is not None and p.rating < MIN_RATING:
        return ProductState.REJECTED, "low_rating"
    return ProductState.CANDIDATE, "passed_qualification"


def _save_score(db: Session, product_id: int, result: ScoreResult) -> None:
    db.add(
        OpportunityScore(
            product_id=product_id,
            score=result.score,
            algorithm_version=result.algorithm_version,
            components=result.components,
            data_available=result.data_available,
            missing_fields=result.missing_fields,
        )
    )


def run_qualification(db: Session, *, limit: int = 200) -> QualificationResult:
    now = datetime.now(UTC)
    rows = db.execute(
        select(Product, ProductCurrentState.state)
        .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .where(ProductCurrentState.state.in_([ProductState.DISCOVERY, ProductState.QUALIFICATION]))
        .order_by(Product.id)
        .limit(limit)
    ).all()

    out = QualificationResult()
    for product, state in rows:
        snap = _latest_snapshot(db, product.id)
        if snap is None:
            continue

        if state is ProductState.DISCOVERY:
            state_machine.transition(
                db,
                product_id=product.id,
                to_state=ProductState.QUALIFICATION,
                reason_code="qualification_started",
                actor=ACTOR,
            )

        item = _to_marketplace_product(product, snap)
        score = compute_opportunity_score(item, now=now)
        _save_score(db, product.id, score)
        out = QualificationResult(
            evaluated=out.evaluated + 1,
            candidates=out.candidates,
            rejected=out.rejected,
            expired=out.expired,
            waiting_data=out.waiting_data,
        )

        target, reason = _verdict(item, now)
        if target is None:
            out.waiting_data.append(product.id)
            continue

        state_machine.transition(
            db,
            product_id=product.id,
            to_state=target,
            reason_code=reason,
            actor=ACTOR,
            metrics_used={
                "opportunity_score": str(score.score),
                "score_data_available": score.data_available,
                "commission_rate": str(item.commission_rate),
                "sales": item.sales,
                "rating": str(item.rating) if item.rating is not None else None,
            },
        )
        {
            ProductState.CANDIDATE: out.candidates,
            ProductState.REJECTED: out.rejected,
            ProductState.EXPIRED: out.expired,
        }[target].append(product.id)

    db.flush()
    return out
