"""Link rastreado para divulgação manual: o canal de WhatsApp não pode mais vender sem origem."""

from dataclasses import replace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.domain import sub_id as sub_id_format
from app.domain.enums import ProductState
from app.domain.state_machine import get_current_state
from app.main import app
from app.models.catalog import Product
from app.models.tracking import AffiliateLink
from app.services import discovery_service, manual_link_service
from app.services.manual_link_service import (
    ManualLinkError,
    ProductNotInCatalog,
    item_id_from,
)

BASE = "https://mp.test"


@pytest.fixture
def product(db: Session) -> Product:
    discovery_service.run_discovery(db, MockAdapter(), limit=1)
    item = db.execute(select(Product).order_by(Product.id).limit(1)).scalar_one()
    item.external_product_id = "23392973710"  # o mock usa "mock-0001"; a Shopee usa só dígitos
    db.flush()
    return item


def _create(db, ref, channel="wa", base=BASE):
    return manual_link_service.create(
        db, MockAdapter(), ref=ref, channel=channel, public_base=base, max_sub_id_length=48
    )


@pytest.mark.parametrize(
    "ref",
    [
        "23392973710",
        "https://shopee.com.br/product/740111576/23392973710",
        "https://shopee.com.br/Protetor-Colchao-i.740111576.23392973710?sp_atk=abc",
    ],
)
def test_item_id_is_read_from_a_plain_id_or_either_url_shape(ref):
    assert item_id_from(ref) == "23392973710"


def test_an_unrecognised_reference_is_refused_with_a_clear_message():
    with pytest.raises(ManualLinkError):
        item_id_from("https://exemplo.com/qualquer-coisa")


def test_the_link_goes_through_our_redirect_and_carries_the_channel(db, product):
    link = _create(db, "https://shopee.com.br/product/1/23392973710", "wa")

    assert link.tracked_url == f"{BASE}/go/{link.sub_id}"
    parts = sub_id_format.parse(link.sub_id)
    assert parts.channel == "wa" and parts.product_id == product.id
    stored = db.execute(
        select(AffiliateLink).where(AffiliateLink.sub_id == link.sub_id)
    ).scalar_one()
    assert stored.utm_medium == "organic"  # WhatsApp não é tráfego pago


def test_asking_twice_returns_the_same_link_instead_of_creating_another(db, product):
    first = _create(db, "23392973710")
    again = _create(db, "23392973710")

    assert first.sub_id == again.sub_id
    assert len(db.execute(select(AffiliateLink)).scalars().all()) == 1


def test_a_product_outside_the_catalog_is_fetched_and_registered_on_the_spot(db):
    class KnowsOneItem(MockAdapter):
        """O marketplace conhece o item 55500011122, mas a descoberta nunca o trouxe."""

        def get_product(self, external_product_id):
            offer = self.search_products(limit=1)[0]
            return replace(offer, external_product_id="55500011122")

    made = manual_link_service.create(
        db, KnowsOneItem(), ref="https://shopee.com.br/product/9/55500011122", channel="wa",
        public_base=BASE, max_sub_id_length=48,
    )

    product = db.get(Product, made.product_id)
    assert product.external_product_id == "55500011122"
    assert get_current_state(db, product.id) is ProductState.DISCOVERY  # segue o funil normal
    assert made.tracked_url == f"{BASE}/go/{made.sub_id}"


def test_an_item_the_marketplace_does_not_know_is_refused(db, product):
    with pytest.raises(ProductNotInCatalog):
        _create(db, "99999999999")


def test_unknown_channel_and_missing_public_base_are_refused(db, product):
    with pytest.raises(ManualLinkError):
        _create(db, "23392973710", channel="google")
    with pytest.raises(ManualLinkError):
        _create(db, "23392973710", base="")


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_endpoint_is_for_people_only(client, db, product):
    body = {"ref": "23392973710", "channel": "wa"}
    n8n = {"X-API-Key": get_settings().n8n_api_key}
    assert client.post("/api/v1/links/manual", json=body, headers=n8n).status_code == 401
    assert client.post("/api/v1/links/manual", json=body).status_code == 401

    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"public_base_url": BASE}
    )
    token = jwt.encode({"email": "dono@example.com"}, get_settings().jwt_secret, algorithm="HS256")
    ok = client.post(
        "/api/v1/links/manual", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert ok.status_code == 200
    assert ok.json()["tracked_url"].startswith(f"{BASE}/go/")
    assert ok.json()["channel"] == "wa"
