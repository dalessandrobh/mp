import pytest

from app.core import idempotency
from app.core.exceptions import IdempotencyConflict

ENDPOINT = "/api/v1/ads/campaigns"
PAYLOAD = {"product_id": 42, "daily_budget": "10.00"}


def test_unknown_key_allows_execution(db):
    assert idempotency.lookup(db, key="k-1", endpoint=ENDPOINT, payload=PAYLOAD) is None


def test_same_key_and_body_returns_stored_response(db):
    idempotency.store(
        db,
        key="k-2",
        endpoint=ENDPOINT,
        payload=PAYLOAD,
        response_body={"campaign_id": 7},
    )

    # O retry do n8n devolve a resposta guardada em vez de criar outra campanha.
    assert idempotency.lookup(db, key="k-2", endpoint=ENDPOINT, payload=PAYLOAD) == {
        "campaign_id": 7
    }


def test_same_key_with_different_body_is_a_conflict(db):
    idempotency.store(
        db, key="k-3", endpoint=ENDPOINT, payload=PAYLOAD, response_body={"campaign_id": 7}
    )

    with pytest.raises(IdempotencyConflict):
        idempotency.lookup(
            db, key="k-3", endpoint=ENDPOINT, payload={"product_id": 99, "daily_budget": "50.00"}
        )


def test_hash_ignores_key_order(db):
    assert idempotency.hash_request({"a": 1, "b": 2}) == idempotency.hash_request({"b": 2, "a": 1})
