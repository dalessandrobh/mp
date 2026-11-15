"""Exportação da vitrine: mesma curadoria do pacote diário, em CSV."""

import csv
import io
from decimal import Decimal

import jwt
from fastapi.testclient import TestClient

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.services import showcase_service
from tests.test_content import testing_products  # noqa: F401  (fixture)


def test_rows_respect_limit_and_price_ceiling(db, testing_products):  # noqa: F811
    everything = showcase_service.rows(db, MockAdapter(), limit=10, max_price=None)
    assert len(everything) == 3

    assert len(showcase_service.rows(db, MockAdapter(), limit=2, max_price=None)) == 2
    cheap = showcase_service.rows(db, MockAdapter(), limit=10, max_price=Decimal("1"))
    assert cheap == []


def test_csv_has_header_position_and_commission_in_percent(db, testing_products):  # noqa: F811
    items = showcase_service.rows(db, MockAdapter(), limit=10, max_price=None)
    parsed = list(csv.reader(io.StringIO(showcase_service.to_csv(items))))

    assert parsed[0] == showcase_service.HEADER
    assert [row[0] for row in parsed[1:]] == ["1", "2", "3"]
    first = items[0]
    if first.commission_rate is not None:
        assert Decimal(parsed[1][3]) == (first.commission_rate * 100).quantize(Decimal("0.01"))
    assert parsed[1][5] == first.url


def test_endpoint_is_for_people_only_and_returns_a_csv_file(db, testing_products):  # noqa: F811
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        n8n = {"X-API-Key": get_settings().n8n_api_key}
        assert client.get("/api/v1/links/showcase.csv", headers=n8n).status_code == 401

        token = jwt.encode(
            {"email": "dono@example.com"}, get_settings().jwt_secret, algorithm="HS256"
        )
        ok = client.get(
            "/api/v1/links/showcase.csv?limit=2", headers={"Authorization": f"Bearer {token}"}
        )
        assert ok.status_code == 200
        assert ok.headers["content-type"].startswith("text/csv")
        assert "vitrine.csv" in ok.headers["content-disposition"]
        assert ok.text.startswith("﻿posicao,")
    finally:
        app.dependency_overrides.clear()
