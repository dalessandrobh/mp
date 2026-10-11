import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.models.catalog import Product

KEY = {"X-API-Key": "troque-esta-chave"}


@pytest.fixture
def make_client(db):
    def _make(*, dry_run: bool) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_settings] = lambda: Settings(dry_run=dry_run)
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def _headers(idem: str | None = "k") -> dict:
    h = dict(KEY)
    if idem:
        h["Idempotency-Key"] = idem
    return h


def test_requires_api_key(make_client):
    r = make_client(dry_run=False).post("/api/v1/discovery/run", json={})
    assert r.status_code == 401


def test_requires_idempotency_key(make_client):
    r = make_client(dry_run=False).post("/api/v1/discovery/run", json={}, headers=_headers(None))
    assert r.status_code == 400


def test_discovery_persists_when_not_dry_run(make_client, db):
    r = make_client(dry_run=False).post(
        "/api/v1/discovery/run", json={"limit": 5}, headers=_headers("d-1")
    )
    assert r.status_code == 200
    assert r.json()["new_products"] == 5 and r.json()["dry_run"] is False
    assert db.scalar(select(func.count()).select_from(Product)) == 5


def test_discovery_dry_run_leaves_no_trace(make_client, db):
    r = make_client(dry_run=True).post(
        "/api/v1/discovery/run", json={"limit": 5}, headers=_headers("d-2")
    )
    assert r.json()["dry_run"] is True and r.json()["new_products"] == 5
    assert db.scalar(select(func.count()).select_from(Product)) == 0


def test_global_dry_run_cannot_be_overridden_by_query(make_client, db):
    r = make_client(dry_run=True).post(
        "/api/v1/discovery/run?dry_run=false", json={"limit": 5}, headers=_headers("d-3")
    )
    assert r.json()["dry_run"] is True
    assert db.scalar(select(func.count()).select_from(Product)) == 0


def test_retry_with_same_key_returns_stored_response(make_client, db):
    c = make_client(dry_run=False)
    first = c.post("/api/v1/discovery/run", json={"limit": 5}, headers=_headers("d-4"))
    again = c.post("/api/v1/discovery/run", json={"limit": 5}, headers=_headers("d-4"))
    assert again.json() == first.json()
    assert db.scalar(select(func.count()).select_from(Product)) == 5


def test_same_key_different_body_is_conflict(make_client):
    c = make_client(dry_run=False)
    c.post("/api/v1/discovery/run", json={"limit": 5}, headers=_headers("d-5"))
    r = c.post("/api/v1/discovery/run", json={"limit": 6}, headers=_headers("d-5"))
    assert r.status_code == 409


def test_qualification_after_discovery(make_client):
    c = make_client(dry_run=False)
    c.post("/api/v1/discovery/run", json={"limit": 40}, headers=_headers("q-1"))
    r = c.post("/api/v1/qualification/run", json={}, headers=_headers("q-2"))
    body = r.json()
    assert r.status_code == 200 and body["evaluated"] == 40
    total = sum(len(body[k]) for k in ("candidates", "rejected", "expired", "waiting_data"))
    assert total == 40
