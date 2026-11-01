import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.db.session import get_db
from app.domain import sub_id as sub_id_format
from app.domain.enums import ProductState
from app.domain.state_machine import transition
from app.main import app
from app.models.tracking import AffiliateLink
from app.services import discovery_service, tracking_service


def _count_links(db: Session) -> int:
    return db.execute(select(func.count()).select_from(AffiliateLink)).scalar_one()


def _move_to_test(db: Session, product_id: int) -> None:
    for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
        transition(db, product_id=product_id, to_state=state, reason_code="TEST", actor="system")


@pytest.fixture
def testing_products(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=3)
    from app.models.catalog import Product

    products = db.execute(select(Product).order_by(Product.id).limit(3)).scalars().all()
    for p in products:
        _move_to_test(db, p.id)
    return products


def test_links_only_for_products_that_receive_traffic(db: Session, testing_products):
    # Descoberto mas ainda em DISCOVERY: não ganha link.
    discovery_service.run_discovery(db, MockAdapter(), limit=10)

    result = tracking_service.generate_links(
        db, MockAdapter(), channel="meta", max_sub_id_length=64
    )

    assert result.created == 3
    assert _count_links(db) == 3


def test_generation_is_idempotent(db: Session, testing_products):
    first = tracking_service.generate_links(db, MockAdapter(), channel="meta", max_sub_id_length=64)
    second = tracking_service.generate_links(
        db, MockAdapter(), channel="meta", max_sub_id_length=64
    )

    assert first.created == 3
    assert second.created == 0 and second.already_existing == 3
    assert _count_links(db) == 3


def test_sub_id_resolves_back_to_its_product(db: Session, testing_products):
    tracking_service.generate_links(db, MockAdapter(), channel="meta", max_sub_id_length=64)
    link = db.execute(select(AffiliateLink).order_by(AffiliateLink.id)).scalars().first()

    assert sub_id_format.parse(link.sub_id).product_id == link.product_id
    assert tracking_service.resolve_product_id(db, link.sub_id) == link.product_id
    assert tracking_service.resolve_product_id(db, "shp-c0000-p0zzzz-cr00-meta-20260101") is None


def test_too_short_limit_fails_loud_per_product_without_creating_links(db, testing_products):
    result = tracking_service.generate_links(
        db, MockAdapter(), channel="meta", max_sub_id_length=20
    )

    assert result.created == 0
    assert result.failed == 3
    assert "SUBID_MAX_LENGTH" in result.warnings[0]


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "troque-esta-chave"}
URL = "/api/v1/trigger/links/generate?dry_run=false"


def test_endpoint_requires_idempotency_key(client: TestClient):
    assert client.post(URL, headers=HEADERS).status_code == 400


def test_same_key_replays_the_stored_response(client, db, testing_products):
    headers = {**HEADERS, "Idempotency-Key": "k-1"}

    first = client.post(URL, headers=headers)
    second = client.post(URL, headers=headers)

    assert first.status_code == 200
    assert first.json()["summary"]["created"] == 3
    assert second.json() == first.json()
    assert _count_links(db) == 3


def test_same_key_with_different_body_conflicts(client, db, testing_products):
    headers = {**HEADERS, "Idempotency-Key": "k-2"}
    client.post(URL, headers=headers)

    response = client.post(URL, headers=headers, json={"channel": "whatsapp"})

    assert response.status_code == 409


def test_dry_run_creates_nothing_and_does_not_burn_the_key(client, db, testing_products):
    headers = {**HEADERS, "Idempotency-Key": "k-3"}

    dry = client.post("/api/v1/trigger/links/generate?dry_run=true", headers=headers)
    assert dry.json()["summary"]["created"] == 3
    assert _count_links(db) == 0

    real = client.post("/api/v1/trigger/links/generate?dry_run=false", headers=headers)
    assert real.json()["summary"]["created"] == 3
    assert _count_links(db) == 3
