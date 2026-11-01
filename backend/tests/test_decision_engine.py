from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.db.session import get_db
from app.domain.enums import DecisionType, PortfolioTier, ProductState, SettlementStatus
from app.main import app
from app.models.ai import AiDecision, AiRecommendation
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.metrics import PerformanceDaily
from app.models.portfolio import PortfolioProduct
from app.services import (
    decision_engine,
    discovery_service,
    opportunity_scoring,
    qualification_service,
)
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


def _count(db: Session, model, *where) -> int:
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


@pytest.fixture
def candidates(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


def _enter_portfolio(db: Session, product, *, days_ago: int) -> None:
    db.add(
        PortfolioProduct(
            product_id=product.id,
            tier=PortfolioTier.EXPLORATION,
            entered_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    db.flush()


def _perf(db: Session, product, *, settlement, revenue_available=True, revenue="40.00") -> None:
    db.add(
        PerformanceDaily(
            metric_date=datetime.now(UTC).date() - timedelta(days=2),
            product_id=product.id,
            channel="meta",
            impressions=20000,
            clicks=300,
            ad_spend=Decimal("100.00"),
            conversions=4,
            revenue=Decimal(revenue) if revenue_available else None,
            revenue_data_available=revenue_available,
            cost_data_available=True,
            settlement=settlement,
        )
    )
    db.flush()


def test_promote_recommendations_fill_only_free_exploration_slots(db: Session, candidates):
    result = decision_engine.analyze(db, PARAMS)

    promotes = db.execute(
        select(AiRecommendation).where(AiRecommendation.decision_type == DecisionType.PROMOTE)
    ).scalars().all()
    assert len(promotes) == 3  # 30% de R$100 / R$10 por teste
    assert result.recommendations_created >= 3


def test_analysis_is_idempotent(db: Session, candidates):
    first = decision_engine.analyze(db, PARAMS)
    second = decision_engine.analyze(db, PARAMS)

    assert first.recommendations_created > 0
    assert second.recommendations_created == 0
    assert second.recommendations_skipped_duplicate == first.recommendations_created


def test_recommend_mode_changes_no_state_and_writes_no_decision(db: Session, candidates):
    transitions = _count(db, ProductStateTransition)
    decisions = _count(db, AiDecision)
    portfolio = _count(db, PortfolioProduct)

    decision_engine.analyze(db, PARAMS)

    assert _count(db, ProductStateTransition) == transitions
    assert _count(db, AiDecision) == decisions
    assert _count(db, PortfolioProduct) == portfolio


def test_settled_losing_product_gets_a_replace_recommendation_with_diagnosis(db, product):
    _enter_portfolio(db, product, days_ago=10)
    _perf(db, product, settlement=SettlementStatus.SETTLED)

    result = decision_engine.analyze(db, PARAMS)

    rec = db.execute(
        select(AiRecommendation).where(AiRecommendation.subject_id == str(product.id))
    ).scalar_one()
    assert result.zones["UNDERPERFORMER"] == 1
    assert rec.decision_type in (DecisionType.REPLACE, DecisionType.KEEP)
    assert rec.rationale["diagnosis"]
    assert rec.rationale["data_used"]["settlement"] == "SETTLED"


def test_provisional_or_missing_revenue_never_triggers_replacement(db, product):
    _enter_portfolio(db, product, days_ago=10)
    _perf(db, product, settlement=SettlementStatus.PROVISIONAL)

    decision_engine.analyze(db, PARAMS)

    assert _count(db, AiRecommendation, AiRecommendation.subject_id == str(product.id)) == 0


def test_no_data_product_is_never_replaced(db, product):
    _enter_portfolio(db, product, days_ago=10)
    _perf(db, product, settlement=SettlementStatus.SETTLED, revenue_available=False)

    result = decision_engine.analyze(db, PARAMS)

    assert result.zones["NO_DATA"] == 1
    assert _count(db, AiRecommendation, AiRecommendation.subject_id == str(product.id)) == 0


def test_candidate_state_is_untouched_by_analysis(db: Session, candidates):
    before = _count(db, ProductCurrentState, ProductCurrentState.state == ProductState.CANDIDATE)

    decision_engine.analyze(db, PARAMS)

    assert (
        _count(db, ProductCurrentState, ProductCurrentState.state == ProductState.CANDIDATE)
        == before
    )


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "troque-esta-chave"}


def test_sizing_endpoint_reports_range_without_cpc(client: TestClient):
    response = client.get("/api/v1/portfolio/sizing", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["data_available"] is False
    assert body["recommended_size"] is None


def test_read_endpoints_reject_anonymous_callers(client: TestClient):
    assert client.get("/api/v1/portfolio").status_code == 401
    assert client.get("/api/v1/recommendations").status_code == 401


def test_analyze_endpoint_dry_run_persists_no_recommendation(client, db, candidates):
    response = client.post("/api/v1/portfolio/analyze?dry_run=true", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["summary"]["recommendations_created"] >= 3
    assert _count(db, AiRecommendation) == 0


def test_analyze_endpoint_real_run_lists_pending_recommendations(client, db, candidates):
    client.post("/api/v1/portfolio/analyze?dry_run=false", headers=HEADERS)

    body = client.get("/api/v1/recommendations", headers=HEADERS).json()

    assert len(body["items"]) >= 3
    assert all(item["rationale"].get("engine_version") for item in body["items"])
