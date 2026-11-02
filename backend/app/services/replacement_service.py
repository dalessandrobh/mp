"""Substituição inteligente: o diagnóstico direciona a escolha do substituto (§8.2)."""

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.domain.enums import ProductState
from app.domain.zones import Diagnosis
from app.services import category_quota
from app.services._funnel_queries import latest_snapshot, products_in_state
from app.services.opportunity_scoring import latest_score


@dataclass(frozen=True)
class Candidate:
    product_id: int
    score: Decimal
    commission_rate: Decimal | None


@dataclass(frozen=True)
class ReplacementChoice:
    chosen: Candidate | None
    alternatives: tuple[Candidate, ...]
    rule: str


def _eligible(
    db: Session, exclude: set[int], blocked_categories: frozenset[str] = frozenset()
) -> list[Candidate]:
    pool: list[Candidate] = []
    for product in products_in_state(db, ProductState.CANDIDATE):
        score = latest_score(db, product.id)
        # Score indicativo não decide entrada.
        if product.id in exclude or score is None or not score.data_available:
            continue
        if category_quota.first_category(product) in blocked_categories:
            continue  # categoria já na cota
        snapshot = latest_snapshot(db, product.id)
        pool.append(
            Candidate(product.id, score.score, snapshot.commission_rate if snapshot else None)
        )
    return sorted(pool, key=lambda c: (-c.score, c.product_id))


def pick_replacement(
    db: Session,
    diagnosis: Diagnosis,
    *,
    exclude: set[int] | None = None,
    blocked_categories: frozenset[str] = frozenset(),
) -> ReplacementChoice:
    pool = _eligible(db, exclude or set(), blocked_categories)
    rule = "maior Opportunity Score"

    if diagnosis is Diagnosis.COMMISSION_INSUFFICIENT:
        # O problema era comissão baixa para o CPC: o substituto tem de pagar mais.
        rates = [c.commission_rate for c in pool if c.commission_rate is not None]
        if not rates:
            return ReplacementChoice(None, (), "comissão acima da mediana (sem dado de comissão)")
        cutoff = median(rates)
        pool = [c for c in pool if c.commission_rate is not None and c.commission_rate > cutoff]
        rule = f"comissão acima da mediana ({cutoff}) e maior Opportunity Score"

    if not pool:
        return ReplacementChoice(None, (), rule)
    return ReplacementChoice(pool[0], tuple(pool[1:4]), rule)
