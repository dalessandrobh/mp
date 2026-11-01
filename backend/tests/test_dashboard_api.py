"""Contrato que o dashboard consome: autorização e respostas enriquecidas."""

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.domain.enums import DecisionType, PortfolioTier
from app.main import app
from app.models.ai import AiRecommendation
from app.models.portfolio import PortfolioProduct


def _token(email: str | None = "ana@x.com", **claims) -> dict:
    payload = {**({"email": email} if email else {}), **claims}
    token = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_production_requires_an_allowlist():
    base = dict(
        app_env="production", n8n_api_key="k" * 32, jwt_secret="s" * 32,
        mock_marketplace=True, mock_ads=True,
    )

    with pytest.raises(ValidationError, match="DASHBOARD_ALLOWED_EMAILS"):
        Settings(_env_file=None, **base)

    ok = Settings(_env_file=None, dashboard_allowed_emails=" Ana@X.com , bia@x.com", **base)
    assert ok.allowed_emails == {"ana@x.com", "bia@x.com"}


def test_valid_jwt_of_someone_not_on_the_list_is_forbidden(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "dashboard_allowed_emails", "ana@x.com")

    assert client.get("/api/v1/portfolio", headers=_token("ana@x.com")).status_code == 200
    assert client.get("/api/v1/portfolio", headers=_token("ANA@x.com")).status_code == 200
    assert client.get("/api/v1/portfolio", headers=_token("intruso@x.com")).status_code == 403


def test_approve_is_also_behind_the_allowlist(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "dashboard_allowed_emails", "ana@x.com")

    response = client.post("/api/v1/recommendations/1/approve", headers=_token("intruso@x.com"))

    assert response.status_code == 403


def test_supabase_anon_key_has_no_identity_and_is_rejected(client):
    assert client.get("/api/v1/portfolio", headers=_token(None, role="anon")).status_code == 401


def test_portfolio_items_carry_title_state_and_current_zone(client, db, product):
    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    db.flush()

    item = client.get("/api/v1/portfolio", headers=_token()).json()["items"][0]

    assert item["title"] == product.title
    assert item["zone"] == "NO_DATA"  # sem receita medida, nunca "UNDERPERFORMER"
    assert item["roi"] is None


def test_recommendations_carry_the_product_title(client, db, product):
    db.add(
        AiRecommendation(
            decision_type=DecisionType.PROMOTE, subject_type="product",
            subject_id=str(product.id), rationale={"action": "ENTER_PORTFOLIO"},
        )
    )
    db.flush()

    item = client.get("/api/v1/recommendations", headers=_token()).json()["items"][0]

    assert item["subject_title"] == product.title
