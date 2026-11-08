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


# ---------------------------------------------------- página /biopinterest (perfil do Pinterest)


def _second_link(db, product, *, channel, sub_id):
    record = AffiliateLink(
        product_id=product.id, channel=channel, sub_id=sub_id,
        raw_url="https://example.test/p-1", short_url="https://s.example.test/xyz",
    )
    db.add(record)
    db.flush()
    return record


@pytest.mark.parametrize("path", ["/l", "/biopinterest"])
def test_both_bio_pages_are_noindex_and_free_of_the_marketplace_brand(
    client, db, product, link, path
):
    _publish(db, product)

    response = client.get(path)

    assert response.status_code == 200
    assert "noindex" in response.headers["x-robots-tag"]
    assert 'name="robots" content="noindex' in response.text
    assert f'href="/go/{link.sub_id}"' in response.text and link.short_url not in response.text
    assert "shopee" not in response.text.lower()
    assert "afiliado" in response.text.lower()


@pytest.mark.parametrize("path", ["/l", "/biopinterest"])
def test_url_validators_that_use_head_get_a_200(client, db, product, link, path):
    """O campo "Site" do perfil do Pinterest pode conferir o endereço com HEAD."""
    _publish(db, product)
    assert client.head(path).status_code == 200


def test_the_pinterest_page_prefers_the_pin_channel_link(client, db, product, link):
    """O clique de quem chega pelo perfil do Pinterest tem de entrar como `pin`."""
    _publish(db, product)
    pin = _second_link(db, product, channel="pin", sub_id="mckp0001pinx1")
    # O link `ig` é mais antigo; o `pin` foi gerado depois. Invertemos de propósito: o `ig`
    # é o mais NOVO, e mesmo assim a página do Pinterest escolhe o `pin`.
    db.execute(
        AffiliateLink.__table__.update().where(AffiliateLink.id == pin.id).values(
            generated_at=link.generated_at.replace(year=link.generated_at.year - 1)
        )
    )
    db.flush()

    assert f'href="/go/{pin.sub_id}"' in client.get("/biopinterest").text
    assert f'href="/go/{link.sub_id}"' in client.get("/l").text  # a página genérica não muda


def test_the_pinterest_page_falls_back_when_the_product_has_no_pin_link(
    client, db, product, link
):
    """Preferir um canal nunca faz o produto sumir da página."""
    _publish(db, product)

    assert f'href="/go/{link.sub_id}"' in client.get("/biopinterest").text  # só há `ig`


@pytest.mark.parametrize("path", ["/biopinterest", "/biopinterest/"])
def test_the_pinterest_page_answers_with_and_without_the_trailing_slash(
    client, db, product, link, path
):
    """O campo "Site" do Pinterest acrescenta a barra; sem rota, o Traefik mandaria a
    requisição para o painel (que pede login) e a página pública pareceria protegida."""
    _publish(db, product)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200
    assert f'href="/go/{link.sub_id}"' in response.text
    assert "noindex" in response.headers["x-robots-tag"]


def test_the_traefik_rule_routes_the_slash_variant_to_the_backend():
    """O FastAPI sozinho não basta: sem a regra no Traefik a barra final cai no painel."""
    from pathlib import Path

    compose_file = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.prod.yml"
    rules = [
        line for line in compose_file.read_text().splitlines()
        if ".rule:" in line and "/privacidade" in line
    ]
    assert len(rules) == 2  # roteador http e https
    for rule in rules:
        assert "Path(`/biopinterest`)" in rule and "Path(`/biopinterest/`)" in rule


def test_robots_txt_also_blocks_the_pinterest_bio_page(client):
    assert "Disallow: /biopinterest" in client.get("/robots.txt").text


# ---- layout da página de bio: paleta, acessibilidade e o que NÃO pode aparecer


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_text_color_pair_meets_the_wcag_aa_contrast(theme):
    """O laranja puro com texto branco dá 3,66:1; por isso botão e preço usam `strong`."""
    from app.api.public.routes.catalog import PALETTE

    c = PALETTE[theme]
    text_on_surface = [
        (c["ink"], c["bg"]), (c["ink"], c["card"]), (c["ink"], c["tint"]),
        (c["muted"], c["bg"]), (c["muted"], c["card"]),
        (c["strong"], c["card"]),            # preço
        (c["on_strong"], c["strong"]),       # texto do botão
    ]
    for foreground, background in text_on_surface:
        assert _contrast(foreground, background) >= 4.5, (theme, foreground, background)


def test_the_plain_orange_is_only_decorative_because_it_fails_contrast_with_white_text():
    from app.api.public.routes.catalog import PALETTE

    assert _contrast("#FFFFFF", PALETTE["light"]["orange"]) < 4.5
    assert PALETTE["light"]["orange"] != PALETTE["light"]["strong"]


def test_the_page_uses_the_orange_palette(client, db, product, link):
    _publish(db, product)
    body = client.get("/biopinterest").text.lower()

    for color in ("#ee4d2d", "#f69113", "#c93012"):
        assert color in body
    assert "prefers-color-scheme:dark" in body  # tema escuro definido


def test_the_page_has_no_logo_brand_or_marketplace_ui_elements(client, db, product, link):
    """Só as cores: sem logo, sem nome, sem imagem de marca, sem selo de loja."""
    _publish(db, product)
    body = client.get("/biopinterest").text.lower()

    assert "<svg" not in body and "<canvas" not in body
    assert "logo" not in body
    # Nem a marca nem selos que só a loja oficial usa.
    for forbidden in ("shopee", "mall", "frete grátis", "frete gratis", "oficial"):
        assert forbidden not in body


def test_the_page_does_not_imitate_pinterest(client, db, product, link):
    """Diretrizes de Desenvolvedor 4.7: nada de replicar o visual ou o layout do Pinterest."""
    _publish(db, product)
    body = client.get("/biopinterest").text.lower()

    assert "#e60023" not in body and "#bd081c" not in body  # os vermelhos do Pinterest
    assert "pinterest" not in body                          # nem o nome, nem o P
    # Mosaico de alturas diferentes é a assinatura visual do Pinterest.
    # A grade (`grid-template-columns`) é permitida; as propriedades de colunas CSS não.
    import re

    assert not re.search(r"(?<![\w-])columns\s*:|column-count|column-width", body)
    assert "masonry" not in body


def test_the_disclosure_stays_visible_and_the_page_is_responsive(client, db, product, link):
    _publish(db, product)
    body = client.get("/biopinterest").text

    assert 'class="note"' in body and "link" in body.lower() and "afiliado" in body.lower()
    assert 'name="viewport"' in body and "grid-template-columns" in body
    assert "focus-visible" in body  # navegação por teclado


def test_the_default_subtitle_does_not_claim_the_products_were_tested(client, db, product, link):
    """Ninguém testou os produtos: a afirmação seria informação não verificada."""
    from app.core.config import Settings

    subtitle = Settings(_env_file=None).bio_page_subtitle
    assert "testei" not in subtitle.lower() and "testad" not in subtitle.lower()
    _publish(db, product)
    assert "testei" not in client.get("/biopinterest").text.lower()


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
