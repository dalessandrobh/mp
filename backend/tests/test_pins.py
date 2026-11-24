"""Pins do dia: imagem 2:3 própria, botão "Pin It" e a marca de postado."""

import io
from decimal import Decimal
from urllib.parse import parse_qs, quote, urlparse

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.content import Creative
from app.models.social import SocialPost
from app.services import content_service, pin_image_service, pin_links, pin_service
from tests.test_content import testing_products  # noqa: F401  (usada via usefixtures)

BASE = "https://mp.test"


def _package(db):
    return content_service.generate_daily_package(
        db, MockAdapter(), None, count=3, max_sub_id_length=48,
        llm_cap_usd=Decimal("1.00"), public_base=BASE,
    )


def _png(size, color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def test_pin_it_url_carries_link_image_and_description():
    url = pin_links.pin_it_url(link=f"{BASE}/go/abc", image=f"{BASE}/img/7.jpg",
                               description="Olha\n\n#publi")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.pinterest.com/pin/create/button/?")
    assert query["url"] == [f"{BASE}/go/abc"]
    assert query["media"] == [f"{BASE}/img/7.jpg"]
    assert query["description"] == ["Olha\n\n#publi"]


@pytest.mark.parametrize("size", [(800, 800), (400, 1200), (1600, 900)])
def test_image_is_rendered_on_a_2_3_canvas_without_cropping(size):
    out = Image.open(io.BytesIO(pin_image_service.render(_png(size))))
    assert out.size == (1000, 1500)
    assert out.format == "JPEG"
    assert out.getpixel((0, 0)) == (255, 255, 255)  # fundo branco nas bordas


def test_transparent_png_is_flattened_on_white():
    raw = io.BytesIO()
    Image.new("RGBA", (500, 500), (0, 0, 0, 0)).save(raw, format="PNG")
    out = Image.open(io.BytesIO(pin_image_service.render(raw.getvalue())))
    assert out.getpixel((500, 750)) == (255, 255, 255)


def test_garbage_bytes_are_refused():
    with pytest.raises(pin_image_service.ImageUnavailable):
        pin_image_service.render(b"isto nao e imagem")


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://cf.shopee.com.br/file/abc", True),
        ("https://down-br.img.susercontent.com/file/abc", True),
        ("http://cf.shopee.com.br/file/abc", False),
        ("https://evilshopee.com.br/file/abc", False),
        ("https://cf.shopee.com.br.evil.com/file/abc", False),
        ("https://169.254.169.254/latest", False),
    ],
)
def test_only_marketplace_image_hosts_are_fetched(url, ok):
    assert pin_image_service.is_allowed(url) is ok


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"public_base_url": BASE}
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        pin_image_service.pin_image.cache_clear()


def _auth():
    token = jwt.encode({"email": "dono@example.com"}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.usefixtures("testing_products")
def test_image_endpoint_serves_the_rendered_product_photo(
    client, db, monkeypatch
):
    _package(db)
    creative = db.execute(select(Creative).order_by(Creative.id)).scalars().first()
    monkeypatch.setattr(pin_image_service, "fetch", lambda url: _png((600, 600)))

    ok = client.get(f"/img/{creative.id}.jpg")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(ok.content)).size == (1000, 1500)

    assert client.get("/img/999999.jpg").status_code == 404


@pytest.mark.usefixtures("testing_products")
def test_image_endpoint_is_404_when_the_photo_cannot_be_fetched(
    client, db, monkeypatch
):
    _package(db)
    creative = db.execute(select(Creative).order_by(Creative.id)).scalars().first()

    def boom(url):
        raise pin_image_service.ImageUnavailable("fora do ar")

    monkeypatch.setattr(pin_image_service, "fetch", boom)
    assert client.get(f"/img/{creative.id}.jpg").status_code == 404


@pytest.mark.usefixtures("testing_products")
def test_package_message_has_the_one_tap_link(db, testing_products):  # noqa: F811
    result = _package(db)
    for package in result.packages:
        assert "Abrir no Pinterest (1 toque)" in package["caption"]
        assert "https://www.pinterest.com/pin/create/button/?" in package["caption"]
        image = quote(f"{BASE}/img/{package['creative_id']}.jpg", safe="")
        assert image in package["caption"]


@pytest.mark.usefixtures("testing_products")
def test_pins_today_lists_cards_and_marking_posted_is_idempotent(client, db, testing_products):  # noqa: F811
    assert client.get("/api/v1/pins/today").status_code == 401
    _package(db)

    body = client.get("/api/v1/pins/today", headers=_auth()).json()
    assert len(body["items"]) == 3 and body["pending"] == 3
    first = body["items"][0]
    assert first["link"].startswith(f"{BASE}/go/") and first["link"].endswith("pin")
    assert first["image_url"] == f"{BASE}/img/{first['creative_id']}.jpg"
    assert first["pin_it_url"].startswith("https://www.pinterest.com/pin/create/button/?")
    assert "#publi" in first["description"]

    done = client.post(f"/api/v1/pins/{first['creative_id']}/posted", headers=_auth())
    assert done.json() == {"creative_id": first["creative_id"], "marked": True}
    again = client.post(f"/api/v1/pins/{first['creative_id']}/posted", headers=_auth())
    assert again.json()["marked"] is False

    after = client.get("/api/v1/pins/today", headers=_auth()).json()
    assert after["pending"] == 2
    assert after["items"][-1]["creative_id"] == first["creative_id"]  # postado vai para o fim
    assert after["items"][-1]["posted"] is True

    post = db.execute(select(SocialPost)).scalar_one()
    assert post.status == "PUBLISHED" and post.external_post_id is None
    assert post.payload["manual"] is True


@pytest.mark.usefixtures("testing_products")
def test_marking_an_unknown_pin_is_refused(client, db, testing_products):  # noqa: F811
    assert client.post("/api/v1/pins/999999/posted", headers=_auth()).status_code == 400


@pytest.mark.usefixtures("testing_products")
def test_card_uses_the_description_stored_with_the_creative(db, testing_products):  # noqa: F811
    _package(db)
    cards = pin_service.recent(db, public_base=BASE)
    for card in cards:
        creative = db.get(Creative, card.creative_id)
        assert card.description == creative.description
