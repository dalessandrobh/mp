"""Anúncios do Pinterest: payloads, moeda, erros por item vs. fatais, e o piso do lance."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ads.base import PAUSED, AdsProviderError
from app.adapters.ads.pinterest.adapter import PinterestAdsAdapter, targeting_spec
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.adapters.social.mock.adapter import MockSocialAdapter
from app.adapters.social.pinterest.auth import PinterestAuth, StoredToken
from app.adapters.social.pinterest.client import PinterestClient
from app.domain.enums import PortfolioTier, ProductState
from app.domain.state_machine import transition
from app.models.catalog import Product
from app.models.scoring import ExpectedValue
from app.models.social import SocialPost
from app.services import (
    content_service,
    discovery_service,
    pinterest_ads_targets,
    publishing_service,
)
from app.services.ads_gateway import (
    AdsGateway,
    BundleRequest,
    BundleStatus,
    ExecutionContext,
    GatewayLimits,
)
from app.services.budget_guard import BudgetGuard
from app.services.pinterest_ads_targets import PinterestAdTargets, Skip
from tests.test_guardrails import PARAMS

ACCOUNT = "549755885175"
BASE = "https://mp.test"


class Recorder:
    """Servidor falso que responde como a API v5 e guarda cada requisição."""

    def __init__(self, *, currency="BRL", status="PAUSED", fail_on=None, exceptions=None):
        self.requests: list[httpx.Request] = []
        self.currency, self.status = currency, status
        self.fail_on, self.exceptions = fail_on, exceptions

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v5")
        if self.fail_on and path.endswith(self.fail_on[0]):
            return httpx.Response(self.fail_on[1], json={"code": 2, "message": "recusado"})
        if request.method == "GET" and path == f"/ad_accounts/{ACCOUNT}":
            return httpx.Response(200, json={"id": ACCOUNT, "currency": self.currency})
        if request.method == "GET" and "/campaigns/" in path:
            return httpx.Response(200, json={"id": "c1", "status": self.status})
        if request.method == "GET" and path.endswith("/ads/analytics"):
            return httpx.Response(
                200,
                json=[
                    {"AD_ID": "9", "DATE": "2026-11-02", "IMPRESSION_1": 1200,
                     "CLICKTHROUGH_1": 30, "SPEND_IN_MICRO_DOLLAR": 4_500_000},
                    {"AD_ID": "9", "DATE": "2026-11-03", "IMPRESSION_1": 10},
                ],
            )
        if request.method == "PATCH":
            return httpx.Response(200, json={"items": [{"data": {"id": "c1"}}]})
        item = {"data": {"id": f"id-{len(self.requests)}"}}
        if self.exceptions:
            item = {"data": None, "exceptions": self.exceptions}
        return httpx.Response(200, json={"items": [item]})

    def bodies(self, suffix: str) -> list:
        return [
            json.loads(r.content)
            for r in self.requests
            if r.method in ("POST", "PATCH") and r.url.path.endswith(suffix)
        ]


def _adapter(recorder: Recorder) -> PinterestAdsAdapter:
    store = type("S", (), {})()
    store.token = StoredToken(refresh_token="r", access_token="a", access_expires_at=9e12)
    auth = PinterestAuth(
        app_id="a", app_secret="s", load=lambda: store.token, save=lambda t: None,
        http=httpx.Client(transport=httpx.MockTransport(recorder)),
    )
    client = PinterestClient(
        auth=auth, http=httpx.Client(transport=httpx.MockTransport(recorder)),
        sleep=lambda s: None, max_retries=0,
    )
    return PinterestAdsAdapter(client=client, ad_account_id=ACCOUNT)


# ---------- payloads ----------


def test_the_account_id_must_be_numeric():
    with pytest.raises(ValueError):
        PinterestAdsAdapter(client=None, ad_account_id="act_123")


def test_campaign_is_created_paused_with_the_click_objective():
    rec = Recorder()
    adapter = _adapter(rec)
    adapter.create_campaign({"name": "mp-x", "status": "ACTIVE", "objective": "OUTCOME_SALES"})

    (body,) = rec.bodies("/campaigns")
    # Mesmo que o chamador peça outra coisa, o adapter só sabe emitir PAUSED e CONSIDERATION.
    assert body == [{"name": "mp-x", "objective_type": "CONSIDERATION", "status": PAUSED}]


def test_ad_group_carries_a_daily_budget_and_bid_in_micro_currency():
    rec = Recorder()
    adapter = _adapter(rec)
    adapter.create_ad_set(
        {"name": "g", "campaign_external_id": "c1", "daily_budget": "12.50", "bid": "0.27"}
    )

    (body,) = rec.bodies("/ad_groups")
    group = body[0]
    assert group["budget_in_micro_currency"] == 12_500_000
    assert group["bid_in_micro_currency"] == 270_000
    assert group["billable_event"] == "CLICKTHROUGH"
    assert group["status"] == PAUSED
    assert group["targeting_spec"] == targeting_spec("BR") == {"GEO": ["BR"], "LOCALE": ["pt"]}


def test_ad_group_without_a_bid_is_refused_before_any_call():
    """A spec exige lance em CONSIDERATION/CLICKTHROUGH; falhar aqui é mais claro que um 400."""
    rec = Recorder()
    with pytest.raises(AdsProviderError, match="lance"):
        _adapter(rec).create_ad_set(
            {"name": "g", "campaign_external_id": "c1", "daily_budget": "10"}
        )
    assert rec.requests == []


def test_ad_promotes_the_pin_and_carries_its_own_destination():
    rec = Recorder()
    _adapter(rec).create_ad(
        {"name": "a", "ad_set_external_id": "g1", "pin_id": "77",
         "destination_url": "https://mp.test/go/xyz"}
    )
    (body,) = rec.bodies("/ads")
    assert body == [{
        "name": "a", "ad_group_id": "g1", "pin_id": "77", "creative_type": "REGULAR",
        "status": PAUSED, "destination_url": "https://mp.test/go/xyz",
    }]


def test_ad_without_a_pin_is_refused():
    with pytest.raises(AdsProviderError, match="pin_id"):
        _adapter(Recorder()).create_ad({"name": "a", "ad_set_external_id": "g1"})


# ---------- moeda ----------


def test_an_account_in_another_currency_refuses_everything_and_is_fatal():
    """R$ 20 em conta de dólar viraria US$ 20 sem nenhum erro."""
    rec = Recorder(currency="USD")
    with pytest.raises(AdsProviderError) as err:
        _adapter(rec).create_campaign({"name": "x"})
    assert err.value.fatal and "USD" in str(err.value)
    assert rec.bodies("/campaigns") == []


def test_the_currency_is_checked_once_not_on_every_call():
    rec = Recorder()
    adapter = _adapter(rec)
    adapter.create_campaign({"name": "a"})
    adapter.create_campaign({"name": "b"})
    gets = [r for r in rec.requests if r.method == "GET"]
    assert len(gets) == 1


# ---------- respostas ----------


def test_an_item_failure_inside_http_200_is_an_error_not_a_created_id():
    rec = Recorder(exceptions=[{"message": "pin não promovível"}])
    with pytest.raises(AdsProviderError, match="pin não promovível") as err:
        _adapter(rec).create_ad({"name": "a", "ad_set_external_id": "g", "pin_id": "1"})
    assert not err.value.fatal


def test_a_400_is_per_item_but_auth_and_5xx_are_fatal():
    with pytest.raises(AdsProviderError) as rejected:
        _adapter(Recorder(fail_on=("/ad_groups", 400))).create_ad_set(
            {"name": "g", "campaign_external_id": "c", "daily_budget": "1", "bid": "0.1"}
        )
    assert not rejected.value.fatal

    with pytest.raises(AdsProviderError) as unauth:
        _adapter(Recorder(fail_on=("/campaigns", 401))).create_campaign({"name": "x"})
    assert unauth.value.fatal

    with pytest.raises(AdsProviderError) as down:
        _adapter(Recorder(fail_on=("/campaigns", 503))).create_campaign({"name": "x"})
    assert down.value.fatal


def test_status_is_reread_from_the_provider_and_pause_is_a_patch():
    rec = Recorder(status="ACTIVE")
    adapter = _adapter(rec)
    assert adapter.get_campaign_status("c1") == "ACTIVE"
    adapter.pause_campaign("c1")
    assert rec.bodies("/campaigns")[-1] == [{"id": "c1", "status": PAUSED}]


# ---------- insights ----------


def test_insights_convert_micro_spend_and_keep_missing_columns_as_none():
    rec = Recorder()
    rows = _adapter(rec).fetch_insights(
        external_ad_ids=["9"], since=date(2026, 11, 2), until=date(2026, 11, 3)
    )
    first, second = rows
    assert (first.impressions, first.clicks, first.spend) == (1200, 30, Decimal("4.50"))
    # O Pinterest não devolveu clique nem gasto: isso NÃO é "custou zero".
    assert (second.clicks, second.spend) == (None, None)
    query = dict(rec.requests[-1].url.params)
    assert query["granularity"] == "DAY" and query["ad_ids"] == "9"


def test_insights_are_requested_in_chunks_of_250_ids():
    rec = Recorder()
    ids = [str(i) for i in range(1, 521)]
    day = date(2026, 11, 1)
    _adapter(rec).fetch_insights(external_ad_ids=ids, since=day, until=day)
    calls = [r for r in rec.requests if r.url.path.endswith("/ads/analytics")]
    assert [len(r.url.params["ad_ids"].split(",")) for r in calls] == [250, 250, 20]


# ---------- gateway ----------


def _gateway(db, adapter):
    limits = GatewayLimits(max_unreviewed=10, max_per_execution=5, dry_run=False, autonomy_level=4)
    return AdsGateway(db, adapter, BudgetGuard(db, PARAMS), limits, ExecutionContext())


def _bundle(product, link, **extra):
    return BundleRequest(
        product_id=product.id, affiliate_link_id=link, name="mp-x",
        daily_budget=Decimal("10"), tier=PortfolioTier.EXPLORATION, **extra,
    )


def _make_pinned(db: Session, **publish_options):
    """Dois produtos em TEST, com legenda do dia, publicados no canal `pin` (mock)."""
    discovery_service.run_discovery(db, MockAdapter(), limit=2)
    products = db.execute(select(Product).order_by(Product.id).limit(2)).scalars().all()
    for p in products:
        p.image_url = f"https://img.test/{p.id}.jpg"
        for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
            transition(db, product_id=p.id, to_state=state, reason_code="T", actor="system")
    db.flush()
    content_service.generate_daily_package(
        db, MockAdapter(), None, count=2, max_sub_id_length=48,
        llm_cap_usd=Decimal("1.00"), public_base=BASE,
    )
    options = {
        "public_base": BASE, "max_sub_id_length": 48, "max_per_run": 10,
        "dry_run": False, "price_ceiling": 100000.0,
    }
    options.update(publish_options)
    publishing_service.publish_pending(db, MockSocialAdapter(), MockAdapter(), **options)
    return products


@pytest.fixture
def pinned(db: Session):
    return _make_pinned(db)


def _ev(db, product, *, commission="30.00", cvr_lower="0.010000"):
    db.add(ExpectedValue(
        product_id=product.id, algorithm_version="ev_v1", ev_per_click=Decimal("0.5"),
        commission_value=Decimal(commission), cvr_estimate=Decimal("0.02"),
        cvr_lower=Decimal(cvr_lower), cvr_upper=Decimal("0.04"), alpha=Decimal("5"),
        beta=Decimal("100"), clicks=0, conversions=0, prior_source="shaped", components={},
        data_available=False,
    ))
    db.flush()


def test_the_gateway_failing_at_the_ad_leaves_an_alert_with_the_orphan_id(db, pinned):
    rec = Recorder(fail_on=("/ads", 400))
    outcome = _gateway(db, _adapter(rec)).create_campaign_bundle(
        _bundle(pinned[0], 1, pin_id="77", bid=Decimal("0.2"))
    )
    assert outcome.status is BundleStatus.FAILED_PROVIDER
    assert not outcome.fatal
    # A campanha existe no Pinterest; o alerta carrega o id para o operador apagá-la.
    from app.models.control import Alert

    alert = db.execute(select(Alert).where(Alert.code == "CAMPAIGN_ORPHANED")).scalar_one()
    assert alert.subject_id == outcome.external_campaign_id


def test_the_gateway_reports_a_fatal_provider_error_without_raising(db, pinned):
    outcome = _gateway(db, _adapter(Recorder(fail_on=("/campaigns", 401)))).create_campaign_bundle(
        _bundle(pinned[0], 1)
    )
    assert outcome.status is BundleStatus.FAILED_PROVIDER and outcome.fatal


# ---------- resolvedor de alvos ----------


def _targets(db, max_cpc="0.30", base=BASE):
    return PinterestAdTargets(
        db, MockAdapter(), public_base=base, max_sub_id_length=48, max_cpc=Decimal(max_cpc)
    )


def test_a_product_without_a_published_pin_gets_no_ad(db):
    discovery_service.run_discovery(db, MockAdapter(), limit=1)
    product = db.execute(select(Product)).scalars().first()
    _ev(db, product)
    assert _targets(db).resolve(product) == Skip("sem pin publicado")


def test_a_blocked_post_does_not_become_an_ad(db):
    """O guarda de réplica barra no pin; o anúncio herda isso, sem regra duplicada."""
    # Teto de preço quase zero + toda categoria do mock como "de risco": nada passa.
    every_category = frozenset({"Casa", "Eletrônicos", "Beleza", "Esporte", "Moda"})
    products = _make_pinned(db, price_ceiling=0.01, brand_categories=every_category)
    blocked = db.execute(select(SocialPost).where(SocialPost.status == "BLOCKED")).scalars().all()
    assert blocked, "pré-condição: o guarda precisa ter barrado ao menos um pin"

    barred = db.get(Product, blocked[0].product_id)
    _ev(db, barred)
    assert _targets(db).resolve(barred) == Skip("sem pin publicado")
    assert products


def test_the_ad_gets_its_own_channel_link_and_destination(db, pinned):
    product = pinned[0]
    _ev(db, product)
    target = _targets(db).resolve(product)

    assert not isinstance(target, Skip)
    from app.models.tracking import AffiliateLink

    link = db.get(AffiliateLink, target.affiliate_link_id)
    assert link.channel == "pinads"
    assert target.destination_url == f"{BASE}/go/{link.sub_id}"
    # E o link do pin orgânico continua sendo outro.
    organic = db.execute(select(AffiliateLink).where(
        AffiliateLink.product_id == product.id, AffiliateLink.channel == "pin")).scalar_one()
    assert organic.id != link.id


def test_the_bid_is_the_revenue_floor_when_that_is_below_the_cap(db, pinned):
    _ev(db, pinned[0], commission="30.00", cvr_lower="0.005000")  # piso = 0,15
    assert _targets(db, max_cpc="0.30").resolve(pinned[0]).bid == Decimal("0.15")


def test_the_bid_is_capped_when_the_floor_is_high(db, pinned):
    _ev(db, pinned[0], commission="100.00", cvr_lower="0.020000")  # piso = 2,00
    assert _targets(db, max_cpc="0.30").resolve(pinned[0]).bid == Decimal("0.30")


def test_a_floor_that_rounds_to_zero_buys_nothing(db, pinned):
    _ev(db, pinned[0], commission="1.00", cvr_lower="0.001000")  # piso = 0,00
    result = _targets(db).resolve(pinned[0])
    assert isinstance(result, Skip) and "piso" in result.reason


def test_no_ev_no_ad(db, pinned):
    assert _targets(db).resolve(pinned[0]) == Skip("sem EV calculado")


def test_no_public_base_no_ad(db, pinned):
    _ev(db, pinned[0])
    assert _targets(db, base="").resolve(pinned[0]) == Skip("sem PUBLIC_BASE_URL")


def test_resolving_twice_does_not_create_a_second_link(db, pinned):
    _ev(db, pinned[0])
    first = _targets(db).resolve(pinned[0])
    second = _targets(db).resolve(pinned[0])
    assert first.affiliate_link_id == second.affiliate_link_id


def test_the_ad_channel_survives_a_sub_id_round_trip_and_differs_from_the_organic_one():
    """A ingestão recupera o canal do sub_id; `pinads` e `pin` precisam voltar distintos."""
    from app.domain import sub_id

    def channel_of(channel):
        built = sub_id.build(
            marketplace_prefix="mp0", product_id=7, channel=channel, day=date(2026, 11, 3),
            creative_id=1, max_length=48,
        )
        return sub_id.parse(built).channel

    assert channel_of(pinterest_ads_targets.CHANNEL) == "pinads"
    assert channel_of(pinterest_ads_targets.ORGANIC_CHANNEL) == "pin"


# ---------- serviço de criação ----------


def _create(db, adapter, targets):
    from app.services.ads_creation_service import create_campaigns

    return create_campaigns(db, _gateway(db, adapter), PARAMS, targets)


def test_only_products_with_a_pin_and_an_ev_get_a_campaign(db, pinned):
    from app.adapters.ads.mock.adapter import MockAdsAdapter

    _ev(db, pinned[0])  # o segundo produto fica sem EV
    adapter = MockAdsAdapter()
    result = _create(db, adapter, _targets(db))

    assert result.created == 1 and result.eligible == 1
    assert result.skipped == {"sem EV calculado": 1}
    kinds = [name for name, _ in adapter.calls]
    assert kinds == ["create_campaign", "create_ad_set", "create_ad"]
    ad_set, ad = adapter.calls[1][1], adapter.calls[2][1]
    # O lance, o pin e o destino de canal próprio chegam ao provedor.
    assert Decimal(ad_set["bid"]) == Decimal("0.30")
    assert ad["pin_id"] and "/go/" in ad["destination_url"]


def test_a_fatal_provider_error_stops_the_batch_instead_of_hammering_the_provider(db, pinned):
    _ev(db, pinned[0])
    _ev(db, pinned[1])
    rec = Recorder(fail_on=("/campaigns", 401))
    result = _create(db, _adapter(rec), _targets(db))

    assert result.created == 0 and result.failed_provider == 1
    # Só uma tentativa de criação: o segundo produto nem foi tentado.
    assert len(rec.bodies("/campaigns")) == 1


def test_a_per_item_rejection_does_not_stop_the_next_product(db, pinned):
    _ev(db, pinned[0])
    _ev(db, pinned[1])
    rec = Recorder(fail_on=("/ads", 400))
    result = _create(db, _adapter(rec), _targets(db))

    assert result.failed_provider == 2 and result.created == 0
    assert len(rec.bodies("/campaigns")) == 2


def test_the_default_path_without_targets_is_unchanged(db, pinned):
    """Mock e Meta seguem usando o último link do produto, sem exigir pin."""
    from app.adapters.ads.mock.adapter import MockAdsAdapter

    result = _create(db, MockAdsAdapter(), None)
    assert result.created == 2 and result.skipped == {}


# ---------- configuração ----------


def test_real_pinterest_ads_require_the_account_and_a_public_base():
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {"mock_ads": False, "ads_provider": "pinterest", "pinterest_app_id": "a",
            "pinterest_app_secret": "s"}
    with pytest.raises(ValidationError, match="PINTEREST_AD_ACCOUNT_ID"):
        Settings(_env_file=None, **base)
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
        Settings(_env_file=None, pinterest_ad_account_id="123", **base)
    ok = Settings(_env_file=None, pinterest_ad_account_id="123",
                  public_base_url="https://mp.test", **base)
    assert ok.ads_provider == "pinterest"


def test_the_registry_builds_the_real_adapter_only_with_a_token_store():
    from app.adapters.ads.registry import get_ads_adapter
    from app.core.config import Settings

    settings = Settings(
        _env_file=None, mock_ads=False, ads_provider="pinterest", pinterest_app_id="a",
        pinterest_app_secret="s", pinterest_ad_account_id=ACCOUNT, public_base_url=BASE,
    )
    with pytest.raises(ValueError, match="token_store"):
        get_ads_adapter(settings)
    store = type("S", (), {"load": lambda self: None, "save": lambda self, t: None})()
    assert isinstance(get_ads_adapter(settings, token_store=store), PinterestAdsAdapter)
