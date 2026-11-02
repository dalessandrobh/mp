"""Contagem de clique: o redirect, a deduplicação, o bot e a chegada ao performance_daily."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.enums import ProductState, RunStatus, SettlementStatus
from app.domain.state_machine import transition
from app.main import app
from app.models.control import WorkflowRun
from app.models.metrics import ConversionRaw, PerformanceDaily
from app.models.tracking import AffiliateLink, LinkClick
from app.services import click_service, consolidation_service
from app.services.ingestion_service import SOURCE_CONVERSION

CHROME = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
TODAY = datetime.now(click_service.TZ).date()


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        # raise_server_exceptions=False: queremos a resposta, não a exceção, como em produção.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def link(db: Session, product) -> AffiliateLink:
    record = AffiliateLink(
        product_id=product.id,
        channel="ig",
        sub_id="mckp0001igx1",
        raw_url="https://example.test/p-1",
        short_url="https://s.example.test/abc",
    )
    db.add(record)
    db.flush()
    return record


# ------------------------------------------------------------------ redirect


def test_redirect_sends_to_the_affiliate_link_and_counts_the_click(client, db, link):
    response = client.get(
        f"/go/{link.sub_id}", headers={"user-agent": CHROME}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == link.short_url
    # Os Termos 4.3(k) proíbem indexar URL com ID de afiliado.
    assert "noindex" in response.headers["x-robots-tag"]
    assert "no-store" in response.headers["cache-control"]

    click = db.query(LinkClick).one()
    assert click.product_id == link.product_id and click.channel == "ig"
    assert click.is_unique and not click.is_bot
    assert click.click_date == TODAY


def test_unknown_or_revoked_sub_id_is_404_never_a_redirect(client, db, link):
    """Destino só do banco: o contrário faria do nosso domínio um open redirect."""
    assert client.get("/go/naoexiste", follow_redirects=False).status_code == 404

    link.revoked_at = datetime.now(click_service.TZ)
    db.flush()
    assert client.get(f"/go/{link.sub_id}", follow_redirects=False).status_code == 404
    assert db.query(LinkClick).count() == 0


def test_the_ip_is_never_stored(client, db, link):
    response = client.get(
        f"/go/{link.sub_id}",
        headers={"user-agent": CHROME, "x-forwarded-for": "203.0.113.7, 10.0.0.1"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    click = db.query(LinkClick).one()
    assert click.visitor_hash and "203.0.113.7" not in click.visitor_hash
    assert len(click.visitor_hash) == 32


def test_the_redirect_survives_a_failure_to_record(client, db, link, monkeypatch):
    """Analytics perdido se recupera; venda perdida, não."""
    def explode(*args, **kwargs):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(click_service, "record_click", explode)
    response = client.get(
        f"/go/{link.sub_id}", headers={"user-agent": CHROME}, follow_redirects=False
    )

    assert response.status_code == 302 and response.headers["location"] == link.short_url


def test_robots_txt_blocks_the_redirect_and_the_page(client):
    body = client.get("/robots.txt").text
    assert "Disallow: /go/" in body and "Disallow: /l" in body


# ------------------------------------------------------------------ dedupe e bot


def test_the_same_visitor_twice_in_a_day_is_one_click_for_the_cvr(client, db, link):
    for _ in range(3):
        client.get(f"/go/{link.sub_id}", headers={"user-agent": CHROME}, follow_redirects=False)

    clicks = db.query(LinkClick).order_by(LinkClick.id).all()
    assert len(clicks) == 3, "nada se joga fora: o bruto fica"
    assert [c.is_unique for c in clicks] == [True, False, False]


@pytest.mark.parametrize(
    "agent",
    [
        "WhatsApp/2.23.20.0 A",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "TelegramBot (like TwitterBot)",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "curl/8.4.0",
        "",
    ],
)
def test_link_preview_and_crawler_are_not_clicks(agent):
    assert click_service.is_bot(agent)


def test_a_real_browser_is_a_click():
    assert not click_service.is_bot(CHROME)


def test_bot_click_is_recorded_but_out_of_the_count(db, link):
    click_service.record_click(
        db, link, ip="198.51.100.1", user_agent="WhatsApp/2.23", referrer=None, salt="s"
    )
    click_service.record_click(db, link, ip="198.51.100.2", user_agent=CHROME, referrer=None,
                               salt="s")

    assert db.query(LinkClick).count() == 2
    counted = click_service.clicks_by_day(db, since=TODAY, until=TODAY)
    assert counted[(TODAY, link.product_id, "ig")] == {"clicks": 1, "raw_clicks": 2}


def test_the_table_is_append_only(db, link):
    click_service.record_click(db, link, ip="1.1.1.1", user_agent=CHROME, referrer=None, salt="s")
    click = db.query(LinkClick).one()

    with pytest.raises(Exception, match="append-only"):
        db.execute(
            LinkClick.__table__.delete().where(LinkClick.id == click.id)
        )


# ------------------------------------------------------------------ página /l


def _publish(db, product) -> None:
    states = (
        ProductState.DISCOVERY,
        ProductState.QUALIFICATION,
        ProductState.CANDIDATE,
        ProductState.TEST,
    )
    for state in states:
        transition(db, product_id=product.id, to_state=state, reason_code="T", actor="system")
    db.flush()


def test_the_bio_page_is_noindex_and_lists_what_has_a_link(client, db, product, link):
    _publish(db, product)

    response = client.get("/l")

    assert response.status_code == 200
    assert "noindex" in response.headers["x-robots-tag"]
    assert 'name="robots" content="noindex' in response.text
    # O link que aparece é o nosso redirect, nunca o de afiliado.
    assert f'href="/go/{link.sub_id}"' in response.text
    assert link.short_url not in response.text
    assert product.title in response.text


def test_the_bio_page_never_shows_the_marketplace_brand(client, db, product, link):
    """Termos de Afiliados 2.3(a): marca, nome e logo não entram na mídia de afiliado."""
    _publish(db, product)
    assert "shopee" not in client.get("/l").text.lower()


def test_a_product_without_a_link_is_not_on_the_page(client, db, product):
    _publish(db, product)
    body = client.get("/l").text
    assert product.title not in body and "Nenhuma indicação" in body


def test_the_page_states_the_affiliate_relationship(client, db, product, link):
    _publish(db, product)
    assert "afiliado" in client.get("/l").text.lower()


# ------------------------------------------------------------- consolidação


def _cover(db, day: date) -> None:
    """Prova de que o sync cobriu o dia: sem isso receita é None, nunca zero."""
    db.add(
        WorkflowRun(
            workflow_name=consolidation_service.SYNC_WORKFLOW,
            status=RunStatus.SUCCESS,
            dry_run=False,
            summary={"window": {"since": day.isoformat(), "until": day.isoformat()}},
        )
    )
    db.flush()


def test_organic_clicks_become_a_performance_daily_row_in_their_own_channel(db, product, link):
    _cover(db, TODAY)
    click_service.record_click(db, link, ip="1.0.0.1", user_agent=CHROME, referrer=None, salt="s")
    click_service.record_click(db, link, ip="1.0.0.2", user_agent=CHROME, referrer=None, salt="s")
    click_service.record_click(db, link, ip="1.0.0.3", user_agent="WhatsApp/2", referrer=None,
                               salt="s")

    consolidation_service.consolidate(db, since=TODAY, until=TODAY)

    row = db.query(PerformanceDaily).one()
    assert row.channel == "ig" and row.product_id == product.id
    assert row.clicks == 2, "o buscador de pré-visualização não é clique"
    # Orgânico não tem custo de anúncio: None, não zero, para não inflar ROI de pago.
    assert row.ad_spend is None and row.cost_data_available is False
    assert row.impressions is None, "o Instagram não devolve alcance de link"
    assert row.conversions == 0 and row.revenue == 0
    assert row.cvr == 0


def test_the_organic_sale_closes_the_funnel_with_cvr_and_epc(db, product, link, marketplace):
    _cover(db, TODAY)
    for i in range(4):
        click_service.record_click(db, link, ip=f"2.0.0.{i}", user_agent=CHROME, referrer=None,
                                   salt="s")
    db.add(
        ConversionRaw(
            marketplace_id=marketplace.id, source=SOURCE_CONVERSION, external_order_id="o-1",
            sub_id=link.sub_id, conversion_date=TODAY, commission_value=34, order_value=136,
            status="COMPLETED", settlement=SettlementStatus.PROVISIONAL, payload={},
        )
    )
    db.flush()

    consolidation_service.consolidate(db, since=TODAY, until=TODAY)

    row = db.query(PerformanceDaily).one()
    assert row.clicks == 4 and row.conversions == 1
    assert row.cvr == pytest.approx(0.25, abs=1e-5)
    assert row.epc == 34 / 4, "receita por clique: a métrica do orgânico"
    assert row.roi is None, "sem gasto de anúncio não existe ROI"


def test_a_day_without_click_does_not_create_a_row(db, link):
    _cover(db, TODAY)
    yesterday = TODAY - timedelta(days=1)
    consolidation_service.consolidate(db, since=yesterday, until=yesterday)
    assert db.query(PerformanceDaily).count() == 0
