"""Camada EXECUTE: autonomia, dado fresco, tudo-ou-nada e rastro de decisão."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import (
    DecisionMode,
    DecisionType,
    PortfolioTier,
    ProductState,
    SettlementStatus,
)
from app.domain.state_machine import get_current_state, transition
from app.main import app
from app.models.ads import Campaign
from app.models.ai import AiDecision, AiRecommendation
from app.models.catalog import Product
from app.models.control import Alert
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.metrics import PerformanceDaily
from app.models.portfolio import PortfolioProduct
from app.services import (
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


def _ctx(db, *, level=3, dry_run=False, human=False, actor="ai_engine", params=PARAMS):
    return ExecutionContext(
        params=params,
        guard=BudgetGuard(db, params),
        autonomy_level=level,
        dry_run=dry_run,
        actor=actor,
        human_approved=human,
    )


def _count(db, model, *where) -> int:
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


@pytest.fixture
def candidates(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


@pytest.fixture
def enter_recs(db, candidates):
    decision_engine.analyze(db, PARAMS)
    return db.execute(
        select(AiRecommendation).where(AiRecommendation.decision_type == DecisionType.PROMOTE)
        .order_by(AiRecommendation.id)
    ).scalars().all()


# ---------- entrada no portfólio ----------


def test_execute_enters_the_portfolio_through_the_state_machine(db, enter_recs):
    rec = enter_recs[0]
    product_id = int(rec.subject_id)

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.EXECUTED
    assert get_current_state(db, product_id) is ProductState.TEST
    entry = db.execute(
        select(PortfolioProduct).where(PortfolioProduct.product_id == product_id)
    ).scalar_one()
    assert entry.tier is PortfolioTier.EXPLORATION
    assert entry.allocated_daily_budget == PARAMS.min_daily_test_budget
    assert entry.entry_decision_id == outcome.decision_id
    assert rec.status == "EXECUTED" and rec.executed_decision_id == outcome.decision_id


def test_every_execute_decision_has_a_full_rationale(db, enter_recs):
    execution_service.execute(db, enter_recs[0], _ctx(db))

    decision = db.execute(select(AiDecision)).scalar_one()
    assert decision.mode is DecisionMode.EXECUTE
    for key in ("what", "why", "data_used", "thresholds", "alternatives"):
        assert key in decision.payload
    assert decision.payload["what"] and decision.payload["data_used"]


def test_every_state_change_has_a_transition_row_linked_to_the_decision(db, enter_recs):
    outcome = execution_service.execute(db, enter_recs[0], _ctx(db))

    row = db.execute(
        select(ProductStateTransition).where(
            ProductStateTransition.decision_id == outcome.decision_id
        )
    ).scalar_one()
    assert row.to_state is ProductState.TEST and row.actor == "ai_engine"


def test_autonomy_below_3_does_not_execute(db, enter_recs):
    rec = enter_recs[0]

    outcome = execution_service.execute(db, rec, _ctx(db, level=2))

    assert outcome.status is ExecutionStatus.SKIPPED_AUTONOMY
    assert rec.status == "PENDING"
    assert _count(db, AiDecision) == 0 and _count(db, PortfolioProduct) == 0


def test_human_approval_bypasses_the_level_but_not_the_guards(db, enter_recs):
    rec = enter_recs[0]

    outcome = execution_service.execute(
        db, rec, _ctx(db, level=1, human=True, actor="human:ana@x.com")
    )

    assert outcome.status is ExecutionStatus.EXECUTED
    assert db.execute(select(AiDecision)).scalar_one().payload["human_approved"] is True


def test_dry_run_records_the_simulated_decision_but_changes_nothing(db, enter_recs):
    rec = enter_recs[0]
    product_id = int(rec.subject_id)

    outcome = execution_service.execute(db, rec, _ctx(db, dry_run=True))

    assert outcome.status is ExecutionStatus.SIMULATED
    decision = db.execute(select(AiDecision)).scalar_one()
    assert decision.dry_run is True
    assert get_current_state(db, product_id) is ProductState.CANDIDATE
    assert _count(db, PortfolioProduct) == 0
    assert rec.status == "PENDING"


def test_stale_recommendation_expires_instead_of_executing(db, enter_recs):
    rec = enter_recs[0]
    product_id = int(rec.subject_id)
    execution_service.execute(db, rec, _ctx(db))  # primeiro entra de verdade
    twin = AiRecommendation(
        decision_type=DecisionType.PROMOTE, subject_type="product", subject_id=str(product_id),
        rationale={"action": "ENTER_PORTFOLIO", "what": "x", "why": "y", "data_used": {}},
    )
    db.add(twin)
    db.flush()

    outcome = execution_service.execute(db, twin, _ctx(db))

    assert outcome.status is ExecutionStatus.EXPIRED
    assert twin.status == "EXPIRED" and "expired_reason" in twin.rationale
    assert _count(db, PortfolioProduct) == 1


def test_exploration_slots_are_rechecked_at_execution_time(db, candidates):
    decision_engine.analyze(db, PARAMS)
    recs = db.execute(
        select(AiRecommendation).where(AiRecommendation.decision_type == DecisionType.PROMOTE)
    ).scalars().all()
    # Uma recomendação adicional, fabricada: o 4º candidato não cabe nas 3 vagas.
    extra = db.execute(
        select(Product.id).where(Product.id.not_in([int(r.subject_id) for r in recs]))
    ).scalars().first()
    fourth = AiRecommendation(
        decision_type=DecisionType.PROMOTE, subject_type="product", subject_id=str(extra),
        rationale={"action": "ENTER_PORTFOLIO", "what": "x", "why": "y", "data_used": {}},
    )
    db.add(fourth)
    db.flush()

    outcomes = [execution_service.execute(db, r, _ctx(db)) for r in [*recs, fourth]]

    assert [o.status for o in outcomes[:3]] == [ExecutionStatus.EXECUTED] * 3
    assert outcomes[3].status in (ExecutionStatus.BLOCKED, ExecutionStatus.EXPIRED)
    assert _count(db, PortfolioProduct) == 3


def test_failed_execution_leaves_nothing_behind(db, enter_recs, monkeypatch):
    rec = enter_recs[0]

    def explode(*args, **kwargs):
        raise execution_service.ExecutionBlocked("falha no meio")

    monkeypatch.setattr(execution_service, "transition", explode)

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.BLOCKED
    assert _count(db, AiDecision) == 0 and _count(db, PortfolioProduct) == 0
    assert rec.status == "PENDING"


def test_informational_recommendations_are_never_executed(db, candidates):
    rec = AiRecommendation(
        decision_type=DecisionType.RESIZE_PORTFOLIO, subject_type="portfolio",
        subject_id="portfolio", rationale={"action": "RESIZE", "what": "x", "why": "y"},
    )
    db.add(rec)
    db.flush()

    assert execution_service.execute(db, rec, _ctx(db)).status is (
        ExecutionStatus.SKIPPED_INFORMATIONAL
    )


# ---------- substituição ----------


def _losing_product(db, product_id, *, settlement=SettlementStatus.SETTLED, ctr_clicks=300,
                    impressions=20000, conversions=4, revenue="40.00"):
    entry = PortfolioProduct(
        product_id=product_id, tier=PortfolioTier.EXPLORATION,
        entered_at=datetime.now(UTC) - timedelta(days=10),
        allocated_daily_budget=Decimal("10"),
    )
    db.add(entry)
    db.add(
        PerformanceDaily(
            metric_date=datetime.now(UTC).date() - timedelta(days=2), product_id=product_id,
            channel="meta", impressions=impressions, clicks=ctr_clicks,
            ad_spend=Decimal("100.00"), conversions=conversions, revenue=Decimal(revenue),
            revenue_data_available=True, cost_data_available=True, settlement=settlement,
        )
    )
    db.flush()
    return entry


def _first_candidate(db) -> Product:
    return db.execute(
        select(Product)
        .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .where(ProductCurrentState.state == ProductState.CANDIDATE)
        .order_by(Product.id)
    ).scalars().first()


@pytest.fixture
def replace_setup(db, candidates):
    """Um produto em TEST perdendo dinheiro com dado liquidado + candidatos prontos."""
    loser = _first_candidate(db)
    transition(db, product_id=loser.id, to_state=ProductState.TEST, reason_code="T", actor="system")
    entry = _losing_product(db, loser.id)
    decision_engine.analyze(db, PARAMS)
    rec = db.execute(
        select(AiRecommendation).where(
            AiRecommendation.decision_type == DecisionType.REPLACE,
            AiRecommendation.subject_id == str(loser.id),
        )
    ).scalar_one()
    return loser, entry, rec


def test_replacement_swaps_products_atomically_with_diagnosis_and_alert(db, replace_setup):
    loser, entry, rec = replace_setup

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.EXECUTED, outcome.detail
    decision = db.get(AiDecision, outcome.decision_id)
    assert decision.product_out == loser.id and decision.product_in is not None
    assert decision.payload["diagnosis"]
    assert get_current_state(db, loser.id) is ProductState.REPLACED
    assert get_current_state(db, decision.product_in) is ProductState.TEST
    db.refresh(entry)
    assert entry.exited_at is not None and entry.exit_decision_id == decision.id
    assert entry.exit_reason_code.startswith("REPLACED_")
    assert _count(db, Alert, Alert.code == "PRODUCT_REPLACED") == 1
    assert _count(db, Campaign) == 0  # a plataforma não mexe em campanha


def test_replacement_expires_if_data_turned_provisional(db, replace_setup):
    loser, entry, rec = replace_setup
    row = db.execute(
        select(PerformanceDaily).where(PerformanceDaily.product_id == loser.id)
    ).scalar_one()
    row.settlement = SettlementStatus.PROVISIONAL  # a liquidação foi revista
    db.flush()

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.EXPIRED
    assert get_current_state(db, loser.id) is ProductState.TEST
    assert entry.exited_at is None


def test_replacement_is_blocked_without_a_substitute_and_loser_stays(db, replace_setup):
    loser, entry, rec = replace_setup
    # Esgota o pool de substitutos.
    for pid in db.execute(
        select(ProductCurrentState.product_id).where(
            ProductCurrentState.state == ProductState.CANDIDATE
        )
    ).scalars().all():
        transition(
            db, product_id=pid, to_state=ProductState.REJECTED, reason_code="T", actor="system"
        )

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.BLOCKED
    assert "sem candidato" in outcome.detail
    assert get_current_state(db, loser.id) is ProductState.TEST
    assert entry.exited_at is None


# ---------- graduação ----------


def test_winner_in_test_graduates_to_active_exploitation(db, candidates):
    product = _first_candidate(db)
    transition(
        db, product_id=product.id, to_state=ProductState.TEST, reason_code="T", actor="system"
    )
    entry = _losing_product(db, product.id, revenue="300.00", conversions=20)
    decision_engine.analyze(db, PARAMS)
    rec = db.execute(
        select(AiRecommendation).where(
            AiRecommendation.subject_id == str(product.id),
            AiRecommendation.rationale["action"].astext == "GRADUATE",
        )
    ).scalar_one()

    outcome = execution_service.execute(db, rec, _ctx(db))

    assert outcome.status is ExecutionStatus.EXECUTED, outcome.detail
    assert get_current_state(db, product.id) is ProductState.ACTIVE
    assert entry.tier is PortfolioTier.EXPLOITATION


# ---------- endpoints ----------


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


KEY = {"X-API-Key": "troque-esta-chave"}


def _jwt(email="ana@x.com") -> dict:
    token = jwt.encode({"email": email}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_apply_requires_an_idempotency_key(client):
    assert client.post("/api/v1/portfolio/apply", headers=KEY).status_code == 400


def test_apply_at_default_autonomy_executes_nothing(client, db, enter_recs):
    response = client.post(
        "/api/v1/portfolio/apply?dry_run=false", headers={**KEY, "Idempotency-Key": "ap-1"}
    )

    body = response.json()
    assert body["summary"]["SKIPPED_AUTONOMY"] == len(enter_recs)
    assert _count(db, PortfolioProduct) == 0


def test_apply_respects_the_per_run_cap_and_is_idempotent(client, db, enter_recs, set_autonomy):
    set_autonomy(3)
    headers = {**KEY, "Idempotency-Key": "ap-2"}

    first = client.post("/api/v1/portfolio/apply?dry_run=false", headers=headers)
    again = client.post("/api/v1/portfolio/apply?dry_run=false", headers=headers)

    assert first.json()["summary"]["EXECUTED"] == 3
    assert again.json() == first.json()
    assert _count(db, PortfolioProduct) == 3


def test_apply_dry_run_keeps_the_simulated_decisions(client, db, enter_recs, set_autonomy):
    set_autonomy(3)

    response = client.post(
        "/api/v1/portfolio/apply?dry_run=true", headers={**KEY, "Idempotency-Key": "ap-3"}
    )

    assert response.json()["summary"]["SIMULATED"] == 3
    assert _count(db, AiDecision, AiDecision.dry_run.is_(True)) == 3
    assert _count(db, PortfolioProduct) == 0


def test_approve_executes_for_a_human_even_at_level_1(client, db, enter_recs):
    rec = enter_recs[0]

    response = client.post(f"/api/v1/recommendations/{rec.id}/approve", headers=_jwt())

    assert response.status_code == 200, response.text
    assert response.json()["executed"] is True
    db.refresh(rec)
    assert rec.status == "EXECUTED" and rec.reviewed_by == "human:ana@x.com"


def test_approve_requires_dashboard_auth(client, enter_recs):
    assert client.post(f"/api/v1/recommendations/{enter_recs[0].id}/approve").status_code == 401
    assert (
        client.post(f"/api/v1/recommendations/{enter_recs[0].id}/approve", headers=KEY).status_code
        == 401
    )


def test_blocked_approval_is_not_recorded_as_approved(client, db, enter_recs):
    rec = enter_recs[0]
    # Estoura o teto de exploração: a aprovação precisa falhar inteira.
    BudgetGuard(db, PARAMS).commit(Decimal("30"), PortfolioTier.EXPLORATION)

    response = client.post(f"/api/v1/recommendations/{rec.id}/approve", headers=_jwt())

    assert response.status_code == 409
    db.refresh(rec)
    assert rec.status == "PENDING"


def test_reject_marks_reviewer_and_reason(client, db, enter_recs):
    rec = enter_recs[0]

    response = client.post(
        f"/api/v1/recommendations/{rec.id}/reject", headers=_jwt(), json={"reason": "não gosto"}
    )

    assert response.status_code == 200
    db.refresh(rec)
    assert rec.status == "REJECTED" and rec.rationale["rejection_reason"] == "não gosto"
    again = client.post(f"/api/v1/recommendations/{rec.id}/reject", headers=_jwt())
    assert again.status_code == 400


def test_decisions_history_lists_executions(client, db, enter_recs):
    execution_service.execute(db, enter_recs[0], _ctx(db))

    body = client.get("/api/v1/decisions", headers=KEY).json()

    assert len(body["items"]) == 1 and body["items"][0]["mode"] == "EXECUTE"
