"""Calcula e grava a receita esperada por clique de cada produto que pode ocupar um slot.

Monta as quatro entradas do `ev_v1`:

1. `r` (comissão em dinheiro) — do último snapshot. Exato.
2. momento — da série de snapshots, por Theil–Sen (app/domain/momentum.py).
3. evidência própria — cliques e conversões de `performance_daily` na janela.
4. prior da categoria — Bayes empírico por método dos momentos sobre os produtos da mesma
   categoria nível 1 que já têm clique. Enquanto a categoria não tiver amostra, cai no
   prior global: **pooling parcial**, do mais forte para o mais fraco, e cada nível só
   assume o comando quando tem amostra para isso (docs/plano-10k.md §3.2).
"""

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import expected_value, momentum
from app.domain.enums import ProductState
from app.domain.expected_value import CvrPrior, EVInput
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState
from app.models.metrics import PerformanceDaily
from app.models.scoring import ExpectedValue

# Quem disputa slot de publicação ou vaga de portfólio.
SCORED_STATES = (
    ProductState.QUALIFICATION,
    ProductState.CANDIDATE,
    ProductState.TEST,
    ProductState.ACTIVE,
    ProductState.WINNER,
)
EV_WINDOW_DAYS = 30
# Quantos snapshots entram no cálculo do momento. Mais que isso e a tendência de duas
# semanas atrás ainda estaria pesando na de hoje.
MOMENTUM_POINTS = 14
# Amostra mínima para a categoria virar prior. Abaixo disso a média da categoria é ruído
# e trocar o prior global por ela pioraria a estimativa de todo mundo.
MIN_PRODUCTS_FOR_CATEGORY_PRIOR = 5
MIN_CLICKS_FOR_CATEGORY_PRIOR = 200


@dataclass
class EVScoringResult:
    scored: int = 0
    skipped_no_commission: int = 0
    with_own_data: int = 0
    with_momentum: int = 0
    category_priors: int = 0
    warnings: list[str] = field(default_factory=list)


def latest_ev(db: Session, product_id: int) -> ExpectedValue | None:
    return db.execute(
        select(ExpectedValue)
        .where(ExpectedValue.product_id == product_id)
        .order_by(ExpectedValue.computed_at.desc(), ExpectedValue.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_evs(db: Session) -> dict[int, ExpectedValue]:
    """Último EV de cada produto, numa consulta."""
    out: dict[int, ExpectedValue] = {}
    for row in db.execute(
        select(ExpectedValue).order_by(
            ExpectedValue.product_id,
            ExpectedValue.computed_at.desc(),
            ExpectedValue.id.desc(),
        )
    ).scalars():
        out.setdefault(row.product_id, row)
    return out


def _evidence(db: Session, *, since) -> dict[int, tuple[int, int]]:
    """{produto: (cliques, conversões)} na janela, somando todos os canais."""
    rows = db.execute(
        select(
            PerformanceDaily.product_id,
            func.sum(PerformanceDaily.clicks),
            func.sum(PerformanceDaily.conversions),
        )
        .where(PerformanceDaily.metric_date >= since)
        .group_by(PerformanceDaily.product_id)
    ).all()
    return {pid: (int(clicks or 0), int(conv or 0)) for pid, clicks, conv in rows}


def _momentum_by_product(db: Session, product_ids: list[int]) -> dict[int, Decimal]:
    if not product_ids:
        return {}
    series: dict[int, list[tuple[datetime, int | None]]] = {}
    for captured_at, product_id, sales in db.execute(
        select(
            ProductSnapshot.captured_at, ProductSnapshot.product_id, ProductSnapshot.sales_volume
        )
        .where(ProductSnapshot.product_id.in_(product_ids))
        .order_by(ProductSnapshot.product_id, ProductSnapshot.captured_at.desc())
    ).all():
        points = series.setdefault(product_id, [])
        if len(points) < MOMENTUM_POINTS:
            points.append((captured_at, sales))

    out: dict[int, Decimal] = {}
    for product_id, points in series.items():
        result = momentum.compute(points)
        if result is not None and result.relative is not None:
            out[product_id] = result.relative
    return out


def category_priors(db: Session, *, since) -> dict[str, CvrPrior]:
    """Prior de CVR por categoria nível 1, por método dos momentos.

        α₀ + β₀ = m(1−m)/v − 1        α₀ = m(α₀+β₀)

    `m` é a média das taxas por produto e `v` a variância entre produtos. Variância baixa
    significa categoria homogênea, o que gera prior forte; variância alta gera prior fraco.
    É assim que a força do prior deixa de ser um número escolhido à mão.
    """
    rows = db.execute(
        select(
            Product.category_path,
            PerformanceDaily.product_id,
            func.sum(PerformanceDaily.clicks),
            func.sum(PerformanceDaily.conversions),
        )
        .join(Product, Product.id == PerformanceDaily.product_id)
        .where(PerformanceDaily.metric_date >= since)
        .group_by(Product.category_path, PerformanceDaily.product_id)
    ).all()

    by_category: dict[str, list[tuple[int, int]]] = {}
    for path, _product_id, clicks, conversions in rows:
        if not path or not clicks:
            continue
        by_category.setdefault(str(path[0]), []).append((int(clicks), int(conversions or 0)))

    priors: dict[str, CvrPrior] = {}
    for category, samples in by_category.items():
        total_clicks = sum(c for c, _ in samples)
        if len(samples) < MIN_PRODUCTS_FOR_CATEGORY_PRIOR:
            continue
        if total_clicks < MIN_CLICKS_FOR_CATEGORY_PRIOR:
            continue
        rates = [conv / clicks for clicks, conv in samples]
        mean = statistics.fmean(rates)
        variance = statistics.variance(rates) if len(rates) > 1 else 0.0
        if not 0 < mean < 1 or variance <= 0:
            continue
        nu = mean * (1 - mean) / variance - 1
        if nu <= 0:
            continue
        priors[category] = CvrPrior(
            mean=Decimal(str(mean)),
            strength=min(Decimal(str(nu)), expected_value.PRIOR_STRENGTH),
            source=f"categoria {category}",
        )
    return priors


def _products_to_score(db: Session) -> list[Product]:
    return list(
        db.execute(
            select(Product)
            .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
            .where(ProductCurrentState.state.in_(SCORED_STATES))
            .order_by(Product.id)
        ).scalars()
    )


def _latest_snapshots(db: Session, product_ids: list[int]) -> dict[int, ProductSnapshot]:
    out: dict[int, ProductSnapshot] = {}
    if not product_ids:
        return out
    for snapshot in db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id.in_(product_ids))
        .order_by(
            ProductSnapshot.product_id,
            ProductSnapshot.captured_at.desc(),
            ProductSnapshot.id.desc(),
        )
    ).scalars():
        out.setdefault(snapshot.product_id, snapshot)
    return out


def run_ev_scoring(db: Session, *, today=None) -> EVScoringResult:
    today = today or datetime.now(UTC).date()
    since = today - timedelta(days=EV_WINDOW_DAYS - 1)
    result = EVScoringResult()

    products = _products_to_score(db)
    ids = [p.id for p in products]
    snapshots = _latest_snapshots(db, ids)
    evidence = _evidence(db, since=since)
    momenta = _momentum_by_product(db, ids)
    priors = category_priors(db, since=since)
    result.category_priors = len(priors)

    for product in products:
        snapshot = snapshots.get(product.id)
        if snapshot is None or snapshot.commission_value is None:
            result.skipped_no_commission += 1
            continue

        clicks, conversions = evidence.get(product.id, (0, 0))
        category = str(product.category_path[0]) if product.category_path else None
        relative = momenta.get(product.id)

        computed = expected_value.compute(
            EVInput(
                commission_value=snapshot.commission_value,
                price=snapshot.price,
                sales_volume=snapshot.sales_volume,
                rating=snapshot.rating,
                momentum=relative,
                clicks=clicks,
                conversions=conversions,
                category_prior=priors.get(category) if category else None,
            )
        )
        if computed is None:
            result.skipped_no_commission += 1
            continue

        db.add(
            ExpectedValue(
                product_id=product.id,
                algorithm_version=expected_value.ALGORITHM_VERSION,
                ev_per_click=computed.ev_per_click,
                commission_value=computed.commission_value,
                cvr_estimate=computed.cvr_estimate,
                cvr_lower=computed.cvr_lower,
                cvr_upper=computed.cvr_upper,
                alpha=computed.alpha,
                beta=computed.beta,
                clicks=computed.clicks,
                conversions=computed.conversions,
                prior_source=computed.prior_source,
                momentum=relative,
                components=computed.components,
                data_available=computed.data_available,
            )
        )
        result.scored += 1
        result.with_own_data += computed.data_available
        result.with_momentum += relative is not None

    db.flush()
    return result
