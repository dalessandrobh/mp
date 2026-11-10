"""Tela de Parâmetros: mostra o que está valendo, de onde vem e nunca um segredo."""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.control import ConfigParameter


def _auth() -> dict:
    token = jwt.encode({"email": "dono@example.com"}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _items(client) -> dict:
    body = client.get("/api/v1/parameters", headers=_auth()).json()
    return {i["key"]: i for g in body["groups"] for i in g["items"]}


def test_needs_a_logged_in_person(client):
    assert client.get("/api/v1/parameters").status_code == 401
    assert (
        client.get("/api/v1/parameters", headers={"X-API-Key": "troque-esta-chave"}).status_code
        == 401
    )


def test_shows_the_flags_that_keep_the_system_safe(client):
    items = _items(client)

    for key in ("AI_AUTONOMY_LEVEL", "DRY_RUN", "MOCK_SOCIAL", "MOCK_ADS"):
        assert items[key]["source"] == "ambiente"
    assert items["MOCK_SOCIAL"]["value"] in {"sim", "não"}


def test_a_database_value_wins_and_is_labelled_as_such(client, db: Session):
    db.execute(
        update(ConfigParameter)
        .where(ConfigParameter.key == "MAX_DAILY_AD_SPEND")
        .values(value=150)
    )
    db.flush()

    spend = _items(client)["MAX_DAILY_AD_SPEND"]
    assert spend["source"] == "banco" and "150,00" in spend["value"]


def test_flags_a_database_autonomy_the_code_does_not_read(client, db: Session):
    settings = get_settings()
    other = 1 if settings.ai_autonomy_level != 1 else 2
    db.execute(
        update(ConfigParameter)
        .where(ConfigParameter.key == "AI_AUTONOMY_LEVEL")
        .values(value=other)
    )
    db.flush()

    item = _items(client)["AI_AUTONOMY_LEVEL"]
    assert item["value"] == str(settings.ai_autonomy_level)
    assert item["note"] and "não é usada" in item["note"]


def test_never_exposes_a_secret(client):
    settings = get_settings()
    text = client.get("/api/v1/parameters", headers=_auth()).text
    secrets = (
        settings.jwt_secret, settings.n8n_api_key, settings.shopee_secret,
        settings.pinterest_app_secret, settings.anthropic_api_key, settings.gemini_api_key,
        settings.meta_access_token, settings.click_hash_salt,
    )
    for secret in secrets:
        if secret:
            assert secret not in text
