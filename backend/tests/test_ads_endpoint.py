import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import ProductState, RunStatus
from app.domain.state_machine import transition
from app.main import app
from app.models.ads import Ad, Campaign
from app.models.catalog import Product
from app.models.control import BudgetLedger, WorkflowRun
from app.services import discovery_service, tracking_service

HEADERS = {"X-API-Key": "troque-esta-chave", "Idempotency-Key": "ads-1"}
URL = "/api/v1/trigger/ads/create"


@pytest.fixture
def linked_products(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=4)
    products = db.execute(select(Product).order_by(Product.id).limit(4)).scalars().all()
    for p in products:
        for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
            transition(db, product_id=p.id, to_state=state, reason_code="T", actor="system")
    tracking_service.generate_links(db, MockAdapter(), channel="meta", max_sub_id_length=64)
    return products


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def autonomy4(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_autonomy_level", 4)


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_requires_idempotency_key(client):
    assert client.post(URL, headers={"X-API-Key": HEADERS["X-API-Key"]}).status_code == 400


def test_default_autonomy_refuses_to_create(client, db, linked_products):
    response = client.post(f"{URL}?dry_run=false", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["summary"]["created"] == 0
    assert any("nível 4" in w for w in response.json()["warnings"])
    assert _count(db, Campaign) == 0


def test_dry_run_simulates_without_touching_anything(client, db, linked_products, autonomy4):
    response = client.post(f"{URL}?dry_run=true", headers=HEADERS)

    assert response.json()["summary"]["simulated"] == 4
    assert _count(db, Campaign) == 0 and _count(db, BudgetLedger) == 0


def test_creates_at_most_two_campaigns_paused_with_budget_committed(
    client, db, linked_products, autonomy4
):
    response = client.post(f"{URL}?dry_run=false", headers=HEADERS)

    body = response.json()
    assert body["summary"]["created"] == 2
    assert body["summary"]["stopped_by_limit"] is True
    campaigns = db.execute(select(Campaign)).scalars().all()
    assert len(campaigns) == 2
    assert all(c.status == "PAUSED" and c.created_paused for c in campaigns)
    assert _count(db, Ad) == 2
    assert _count(db, BudgetLedger) == 2


def test_replay_with_same_key_does_not_create_more(client, db, linked_products, autonomy4):
    client.post(f"{URL}?dry_run=false", headers=HEADERS)
    again = client.post(f"{URL}?dry_run=false", headers=HEADERS)

    assert again.status_code == 200
    assert _count(db, Campaign) == 2


def test_new_key_skips_products_with_an_ad_and_stops_at_the_exploration_budget(
    client, db, linked_products, autonomy4
):
    client.post(f"{URL}?dry_run=false", headers=HEADERS)
    second = client.post(f"{URL}?dry_run=false", headers={**HEADERS, "Idempotency-Key": "ads-2"})

    # 4 produtos em TEST, mas a fatia de exploração (30% de R$100) só paga 3 de R$10.
    assert _count(db, Campaign) == 3
    assert _count(db, Ad) == 3
    assert second.json()["summary"]["refused"] == 1
    assert any("fatia EXPLORATION" in w for w in second.json()["warnings"])


def test_budget_status_endpoint(client, db, linked_products, autonomy4):
    client.post(f"{URL}?dry_run=false", headers=HEADERS)

    body = client.get("/api/v1/budget/status", headers={"X-API-Key": HEADERS["X-API-Key"]}).json()

    assert body["used"] == "20.00"
    assert body["tiers"]["EXPLORATION"]["used"] == "20.00"


def test_abort_is_recorded_as_aborted_run_with_alert_kept(client, db, linked_products, autonomy4):
    for i in range(11):
        db.add(Campaign(ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED"))
    db.flush()

    response = client.post(f"{URL}?dry_run=false", headers=HEADERS)

    assert response.json()["status"] == "ABORTED"
    assert db.get(WorkflowRun, response.json()["run_id"]).status is RunStatus.ABORTED
