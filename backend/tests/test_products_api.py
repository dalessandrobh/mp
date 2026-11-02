import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.services import discovery_service, opportunity_scoring, qualification_service

KEY = {"X-API-Key": "troque-esta-chave"}
CATALOG = len(MockAdapter().search_products(limit=500))


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def funnel(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


def _get(client, path):
    response = client.get(f"/api/v1/products{path}", headers=KEY)
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_authentication(client):
    assert client.get("/api/v1/products").status_code == 401
    token = jwt.encode({"email": "ana@x.com"}, get_settings().jwt_secret, algorithm="HS256")
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/products", headers=bearer).status_code == 200


def test_list_reports_totals_counts_and_a_page(client, funnel):
    body = _get(client, "")

    assert body["total"] == CATALOG and len(body["items"]) == 25
    assert sum(body["counts"].values()) == CATALOG
    assert {"DISCOVERY", "REJECTED", "CANDIDATE"} <= set(body["counts"])


def test_state_filter_and_the_reason_for_each_rejection(client, funnel):
    body = _get(client, "?state=REJECTED&limit=100")

    assert body["total"] == body["counts"]["REJECTED"] and body["total"] > 0
    assert all(i["state"] == "REJECTED" for i in body["items"])
    reasons = {i["last_reason_code"] for i in body["items"]}
    assert reasons <= {"OUT_OF_STOCK", "PRICE_TOO_LOW", "COMMISSION_TOO_LOW", "LOW_RATING"}
    assert "OUT_OF_STOCK" in reasons


def test_missing_data_is_null_never_zero(client, funnel):
    items = _get(client, "?state=DISCOVERY&limit=100")["items"]

    waiting = [i for i in items if i["snapshot"]["commission_rate"] is None]
    assert waiting  # os produtos do mock sem comissão esperam dado
    assert all(i["snapshot"]["data_available"]["commission_rate"] is False for i in waiting)
    assert all(i["opportunity"] is None for i in waiting)  # nunca foram pontuados


def test_sorting_by_score_puts_unscored_products_last(client, funnel):
    items = _get(client, "?sort=score&limit=100")["items"]

    scores = [float(i["opportunity"]["score"]) if i["opportunity"] else None for i in items]
    scored = [s for s in scores if s is not None]
    assert scored == sorted(scored, reverse=True)
    first_gap = scores.index(None)
    assert all(s is None for s in scores[first_gap:])


def test_min_score_keeps_only_products_at_or_above_it(client, funnel):
    body = _get(client, "?min_score=60&limit=100")

    assert body["total"] > 0
    assert all(float(i["opportunity"]["score"]) >= 60 for i in body["items"])


def test_search_is_case_insensitive_and_scopes_the_state_counts(client, funnel):
    body = _get(client, "?q=cozinha&limit=100")

    assert 0 < body["total"] < CATALOG
    assert all("cozinha" in i["title"].lower() for i in body["items"])
    assert sum(body["counts"].values()) == body["total"]


def test_pagination_does_not_repeat_or_skip(client, funnel):
    first = _get(client, "?sort=recent&limit=10&offset=0")["items"]
    second = _get(client, "?sort=recent&limit=10&offset=10")["items"]

    ids = [i["id"] for i in first + second]
    assert len(ids) == len(set(ids)) == 20


def test_sort_by_commission_and_sales_work(client, funnel):
    by_sales = _get(client, "?sort=sales&limit=100")["items"]
    sales = [
        i["snapshot"]["sales_volume"]
        for i in by_sales
        if i["snapshot"]["sales_volume"] is not None
    ]

    assert sales == sorted(sales, reverse=True)
    assert _get(client, "?sort=commission")["total"] == CATALOG


def test_invalid_filters_are_rejected_with_a_clear_error(client, funnel):
    for bad in ("?sort=banana", "?state=NOPE"):
        assert client.get(f"/api/v1/products{bad}", headers=KEY).status_code == 400
    assert client.get("/api/v1/products?limit=1000", headers=KEY).status_code == 422


def test_product_detail_tells_the_whole_story(client, funnel, db):
    promoted = _get(client, "?state=CANDIDATE&limit=1")["items"][0]

    detail = _get(client, f"/{promoted['id']}")

    assert detail["state"] == "CANDIDATE" and detail["marketplace"] == "mock"
    assert [h["to_state"] for h in reversed(detail["history"])] == [
        "DISCOVERY", "QUALIFICATION", "CANDIDATE",
    ]
    assert detail["history"][0]["reason_code"] == "OPPORTUNITY_SCORE_ABOVE_THRESHOLD"
    assert detail["history"][0]["metrics_used"]["threshold"]
    assert detail["scores"][0]["components"]["demand"]["available"] in (True, False)
    assert detail["snapshots"][0]["price"] is not None
    assert detail["links"] == []


def test_unknown_product_is_404(client):
    assert client.get("/api/v1/products/999999", headers=KEY).status_code == 404
