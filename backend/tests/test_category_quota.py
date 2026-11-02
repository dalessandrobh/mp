import dataclasses
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.domain.enums import DecisionType
from app.models.ai import AiRecommendation
from app.models.catalog import Category, Product, ProductSnapshot
from app.models.portfolio import PortfolioProduct
from app.services import (
    category_quota,
    decision_engine,
    discovery_service,
    execution_service,
    opportunity_scoring,
    qualification_service,
)
from app.services.budget_guard import BudgetGuard
from app.services.execution_service import ExecutionContext, ExecutionStatus
from app.services.portfolio_service import PortfolioParams

PARAMS = PortfolioParams(
    max_daily_ad_spend=Decimal("100"),
    min_daily_test_budget=Decimal("10"),
    exploration_percentage=30,
    min_active_products=3,
    max_active_products=15,
    min_clicks_for_decision=50,
    min_impressions_for_decision=1000,
    min_test_duration_days=3,
)


@pytest.fixture
def candidates(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


def _ctx(db, params):
    return ExecutionContext(
        params=params,
        guard=BudgetGuard(db, params),
        autonomy_level=3,
        dry_run=False,
        actor="ai_engine",
        human_approved=False,
    )


def test_cap_is_a_share_of_the_portfolio_and_never_zero():
    assert category_quota.cap_per_category(15, 40) == 6
    assert category_quota.cap_per_category(3, 10) == 1
    assert category_quota.cap_per_category(1, 1) == 1


def test_recommendations_respect_the_category_quota(db: Session, candidates):
    params = dataclasses.replace(PARAMS, max_active_products=5, max_category_share_pct=20)  # cap 1

    result = decision_engine.analyze(db, params)

    recs = db.execute(
        select(AiRecommendation).where(AiRecommendation.decision_type == DecisionType.PROMOTE)
    ).scalars().all()
    promoted = [r for r in recs if r.rationale.get("action") == "ENTER_PORTFOLIO"]
    categories = [
        category_quota.first_category(db.get(Product, int(r.subject_id))) for r in promoted
    ]
    assert len(promoted) >= 2
    assert len(categories) == len(set(categories))  # no máximo 1 por categoria
    assert result.held_category_quota > 0


def test_execution_blocks_a_category_that_is_already_full(db: Session, candidates):
    params = dataclasses.replace(PARAMS, max_active_products=5, max_category_share_pct=20)
    first = db.execute(
        select(Product).join(ProductSnapshot).where(Product.category_path.is_not(None))
    ).scalars().first()
    same = db.execute(
        select(Product).where(
            Product.id != first.id,
            Product.category_path[1] == first.category_path[0],
        )
    ).scalars().first()
    db.add(PortfolioProduct(product_id=first.id, tier="EXPLORATION"))
    db.flush()
    rec = AiRecommendation(
        decision_type=DecisionType.PROMOTE, subject_type="product", subject_id=str(same.id),
        rationale={"action": "ENTER_PORTFOLIO", "what": "x", "why": "y", "data_used": {}},
    )
    db.add(rec)
    db.flush()

    outcome = execution_service.execute(db, rec, _ctx(db, params))

    assert outcome.status in (ExecutionStatus.BLOCKED, ExecutionStatus.EXPIRED)
    assert db.execute(
        select(func.count()).select_from(PortfolioProduct)
    ).scalar_one() == 1


# ---------- descoberta por categoria ----------


def test_category_discovery_only_pulls_the_requested_category(db: Session):
    result = discovery_service.run_category_discovery(
        db, MockAdapter(), per_category=1000, category_ids=["Casa"]
    )

    assert result.categories == 1 and result.fetched > 0
    paths = db.execute(select(Product.category_path)).scalars().all()
    assert paths and all(p[0] == "Casa" for p in paths)


def test_category_discovery_reads_the_known_level1_categories(db: Session):
    db.add(
        Category(
            marketplace="mock", external_id="Beleza", level=1, name="Beleza",
            name_source="inferido",
        )
    )
    db.flush()

    result = discovery_service.run_category_discovery(db, MockAdapter(), per_category=1000)

    assert result.categories == 1
    assert all(
        p[0] == "Beleza" for p in db.execute(select(Product.category_path)).scalars().all()
    )


def test_one_failing_category_does_not_stop_the_others(db: Session):
    class Flaky(MockAdapter):
        def search_products(self, *, keyword=None, limit=50, category=None, sort=None):
            if category == "Casa":
                raise RuntimeError("boom")
            return super().search_products(
                keyword=keyword, limit=limit, category=category, sort=sort
            )

    result = discovery_service.run_category_discovery(
        db, Flaky(), per_category=1000, category_ids=["Casa", "Beleza"]
    )

    assert result.failed == ("Casa",) and result.categories == 1 and result.fetched > 0


def test_unchanged_offers_do_not_write_a_new_snapshot(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=20)
    before = db.execute(select(func.count()).select_from(ProductSnapshot)).scalar_one()

    again = discovery_service.run_discovery(db, MockAdapter(), limit=20)

    after = db.execute(select(func.count()).select_from(ProductSnapshot)).scalar_one()
    assert after == before
    assert again.snapshots_skipped == again.updated_products == 20
