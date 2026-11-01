"""Funil ponta a ponta contra o MockAdapter e o Postgres real."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.db.session import get_db
from app.domain.enums import ProductState
from app.main import app
from app.models.catalog import Product, ProductSnapshot
from app.models.control import WorkflowRun
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.scoring import OpportunityScore
from app.services import discovery_service, opportunity_scoring, qualification_service

CATALOG = len(MockAdapter().search_products(limit=500))


def _count_in_state(db: Session, state: ProductState) -> int:
    return db.execute(
        select(func.count()).select_from(ProductCurrentState).where(
            ProductCurrentState.state == state
        )
    ).scalar_one()


def test_discovery_registers_every_offer_in_discovery_state(db: Session):
    result = discovery_service.run_discovery(db, MockAdapter(), limit=500)

    assert result.fetched == CATALOG
    assert result.new_products == CATALOG
    assert _count_in_state(db, ProductState.DISCOVERY) >= CATALOG


def test_discovery_twice_adds_snapshots_but_no_duplicate_products(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    products_after_first = db.execute(select(func.count()).select_from(Product)).scalar_one()

    second = discovery_service.run_discovery(db, MockAdapter(), limit=500)

    assert second.new_products == 0
    assert second.updated_products == CATALOG
    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == (
        products_after_first
    )
    assert db.execute(select(func.count()).select_from(ProductSnapshot)).scalar_one() >= (
        2 * CATALOG
    )


def test_missing_commission_waits_in_discovery_and_is_never_rejected(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)

    result = qualification_service.run_qualification(db)

    assert result.waiting > 0
    waiting_ids = [
        p.id
        for p in db.execute(select(Product).where(Product.external_product_id == "mock-0010"))
        .scalars()
    ]
    state = db.execute(
        select(ProductCurrentState.state).where(ProductCurrentState.product_id.in_(waiting_ids))
    ).scalar_one()
    assert state is ProductState.DISCOVERY


def test_qualification_rejects_with_reason_and_is_idempotent(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)

    first = qualification_service.run_qualification(db)
    second = qualification_service.run_qualification(db)

    assert first.qualified > 0 and first.rejected > 0
    # Quem já saiu de DISCOVERY não é reavaliado; só os que aguardavam dado voltam.
    assert second.qualified == 0 and second.rejected == 0
    out_of_stock = db.execute(
        select(func.count()).select_from(ProductStateTransition).where(
            ProductStateTransition.reason_code == "OUT_OF_STOCK"
        )
    ).scalar_one()
    assert out_of_stock > 0


def test_scoring_is_idempotent_and_promotion_respects_threshold(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)

    scored = opportunity_scoring.run_opportunity_scoring(db)
    rescored = opportunity_scoring.run_opportunity_scoring(db)
    promoted = opportunity_scoring.run_promotion(db)

    assert scored.scored > 0
    assert rescored.scored == 0
    assert rescored.skipped_up_to_date == scored.scored
    assert promoted.promoted > 0
    assert _count_in_state(db, ProductState.CANDIDATE) == promoted.promoted
    # Score indicativo (falta dado) não promove.
    assert promoted.held_indicative > 0
    assert db.execute(
        select(func.count()).select_from(OpportunityScore).where(
            OpportunityScore.llm_used.is_(True)
        )
    ).scalar_one() == 0


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "troque-esta-chave"}


def test_triggers_require_api_key(client: TestClient):
    assert client.post("/api/v1/trigger/discovery").status_code == 401


def test_dry_run_reports_work_but_persists_nothing(client: TestClient, db: Session):
    before = db.execute(select(func.count()).select_from(Product)).scalar_one()

    response = client.post("/api/v1/trigger/discovery?dry_run=true", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["new_products"] == 40
    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == before
    run = db.get(WorkflowRun, body["run_id"])
    assert run.dry_run is True and run.status.value == "SUCCESS"


def test_real_run_through_the_whole_funnel(client: TestClient, db: Session):
    for path in (
        "discovery",
        "qualification",
        "scoring/opportunity",
        "candidates/promote",
    ):
        response = client.post(f"/api/v1/trigger/{path}?dry_run=false", headers=HEADERS)
        assert response.status_code == 200, response.text

    assert _count_in_state(db, ProductState.CANDIDATE) > 0
