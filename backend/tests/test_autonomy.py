import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain import autonomy
from app.domain.autonomy import ActionClass
from app.main import app


def test_level_table_matches_the_plan():
    assert autonomy.MIN_LEVEL == {
        ActionClass.PROMOTE_CANDIDATE: 2,
        ActionClass.PORTFOLIO_CHANGE: 3,
        ActionClass.GENERATE_LINKS: 3,
        ActionClass.CREATE_CAMPAIGN: 4,
        ActionClass.PUBLISH_ORGANIC: 4,
        ActionClass.ADJUST_BUDGET: 5,
    }


@pytest.mark.parametrize("action", list(ActionClass))
def test_permission_is_monotonic_in_level(action):
    allowed = [autonomy.permits(level, action) for level in range(1, 6)]

    assert allowed == sorted(allowed)  # uma vez permitido, segue permitido
    assert allowed[-1] is True


def test_no_action_class_can_activate_a_campaign():
    assert not [a for a in ActionClass if "ACTIVAT" in a.value or "LAUNCH" in a.value]


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "troque-esta-chave"}


def test_promotion_endpoint_is_skipped_below_level_2(client):
    response = client.post("/api/v1/trigger/candidates/promote?dry_run=false", headers=HEADERS)

    assert response.json()["status"] == "SKIPPED"
    assert "nível 2" in response.json()["warnings"][0]


def test_link_generation_is_skipped_below_level_3(client):
    response = client.post(
        "/api/v1/trigger/links/generate?dry_run=false",
        headers={**HEADERS, "Idempotency-Key": "aut-1"},
    )

    assert response.json()["status"] == "SKIPPED"


def test_publishing_is_skipped_below_level_4(client):
    """Publicar pin é a primeira ação que fica pública: não sai no nível 3."""
    response = client.post(
        "/api/v1/trigger/content/publish?dry_run=false",
        headers={**HEADERS, "Idempotency-Key": "aut-pub-1"},
    )

    assert response.json()["status"] == "SKIPPED"
    assert "nível 4" in response.json()["warnings"][0]
