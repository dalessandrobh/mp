"""Guardrails de anúncios e orçamento (PLANNING §9.1). Bloqueiam merge se falharem.

Prioridade do projeto: overspending e a regra PAUSED.
"""

import random
import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.ads.base import AdsAdapter
from app.adapters.ads.mock.adapter import MockAdsAdapter
from app.domain import budget
from app.domain.enums import CampaignReviewStatus, PortfolioTier
from app.main import app
from app.models.ads import Campaign
from app.models.control import Alert, BudgetLedger
from app.services.ads_gateway import (
    AdsGateway,
    BundleRequest,
    BundleStatus,
    ExecutionContext,
    GatewayLimits,
)
from app.services.budget_guard import BudgetGuard
from app.services.portfolio_service import PortfolioParams

PARAMS = PortfolioParams(
    max_daily_ad_spend=Decimal("100"),
    min_daily_test_budget=Decimal("10"),
    exploration_percentage=30,
    min_active_products=3,
    max_active_products=15,
    min_clicks_for_decision=50,
    min_impressions_for_decision=1000,
    min_test_duration_days=3,
)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _limits(**overrides) -> GatewayLimits:
    base = dict(max_unreviewed=10, max_per_execution=2, dry_run=False, autonomy_level=4)
    return GatewayLimits(**{**base, **overrides})


def _gateway(db, adapter=None, **limit_overrides):
    adapter = adapter or MockAdsAdapter()
    gateway = AdsGateway(
        db, adapter, BudgetGuard(db, PARAMS), _limits(**limit_overrides), ExecutionContext()
    )
    return gateway, adapter


def _request(product, link=None, budget_value="10", tier=PortfolioTier.EXPLORATION):
    return BundleRequest(
        product_id=product.id,
        affiliate_link_id=link,
        name="mp-teste",
        daily_budget=Decimal(budget_value),
        tier=tier,
    )


@pytest.fixture
def affiliate_link(db: Session, product):
    from app.models.tracking import AffiliateLink

    link = AffiliateLink(
        product_id=product.id,
        channel="meta",
        sub_id="mck-c0000-p000001-cr00-meta-20260101",
        raw_url="https://x.test",
    )
    db.add(link)
    db.flush()
    return link


def _count(db: Session, model, *where) -> int:
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


# ---------- regra PAUSED ----------


def test_campaign_always_created_paused(db, product, affiliate_link):
    gateway, adapter = _gateway(db)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.CREATED
    for name, payload in adapter.calls:
        if name in {"create_campaign", "create_ad_set", "create_ad"}:
            assert payload["status"] == "PAUSED", name
    campaign = db.get(Campaign, outcome.campaign_id)
    assert campaign.status == "PAUSED" and campaign.created_paused is True
    assert campaign.review_status is CampaignReviewStatus.UNREVIEWED


def test_campaign_status_reverified_after_creation(db, product, affiliate_link):
    adapter = MockAdsAdapter(create_as_status="ACTIVE")  # o provedor desobedece
    gateway, _ = _gateway(db, adapter)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.CREATED
    assert ("pause_campaign", {"external_id": outcome.external_campaign_id}) in adapter.calls
    assert db.get(Campaign, outcome.campaign_id).status == "PAUSED"
    alert = db.execute(
        select(Alert).where(Alert.code == "CAMPAIGN_CREATED_NOT_PAUSED")
    ).scalar_one()
    assert alert.severity == "CRITICAL"


def test_unpausable_campaign_aborts_with_critical_alert(db, product, affiliate_link):
    adapter = MockAdsAdapter(create_as_status="ACTIVE", ignore_pause=True)
    gateway, _ = _gateway(db, adapter)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.ABORTED
    assert _count(db, BudgetLedger) == 0  # nada de orçamento comprometido
    assert _count(db, Alert, Alert.code == "CAMPAIGN_CREATED_NOT_PAUSED") == 1


def test_database_rejects_a_campaign_that_was_not_created_paused(db):
    from sqlalchemy.exc import IntegrityError

    db.add(
        Campaign(
            ad_account_id="a", name="n", objective="o", status="ACTIVE", created_paused=False
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_adapter_contract_has_no_way_to_activate():
    forbidden = re.compile(r"activate|resume|enable|unpause|start", re.I)
    methods = [m for m in dir(AdsAdapter) if not m.startswith("_")]

    assert not [m for m in methods if forbidden.search(m)]


def test_no_endpoint_activates_campaign():
    forbidden = re.compile(r"activate|resume|enable|unpause|publish|launch", re.I)
    paths = [getattr(r, "path", "") for r in app.routes]

    assert not [p for p in paths if forbidden.search(p)]
    # Nenhuma rota de campanha aceita escrita que não seja a revisão humana.
    for route in app.routes:
        if "campaign" in getattr(route, "path", ""):
            assert "review" in route.path or route.methods <= {"GET"}


# ---------- choke points ----------


def _python_files():
    return [p for p in APP_DIR.rglob("*.py")]


def test_only_the_gateway_creates_ad_structure():
    allowed = {"services/ads_gateway.py"}
    pattern = re.compile(r"\b(Campaign|AdSet|Ad)\(|\.create_(campaign|ad_set|ad)\(")
    offenders = []
    for path in _python_files():
        rel = path.relative_to(APP_DIR).as_posix()
        if rel in allowed or rel.startswith(("models/", "adapters/ads/")):
            continue
        if pattern.search(path.read_text()):
            offenders.append(rel)

    assert not offenders, f"estrutura de anúncios criada fora do AdsGateway: {offenders}"


def test_only_the_budget_guard_writes_the_ledger():
    offenders = []
    for path in _python_files():
        rel = path.relative_to(APP_DIR).as_posix()
        if rel in {"services/budget_guard.py"} or rel.startswith("models/"):
            continue
        if re.search(r"\bBudgetLedger\(", path.read_text()):
            offenders.append(rel)

    assert not offenders, f"ledger gravado fora do BudgetGuard: {offenders}"


# ---------- limites do gateway ----------


def test_dry_run_calls_nothing(db, product, affiliate_link):
    gateway, adapter = _gateway(db, dry_run=True)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.SIMULATED
    assert adapter.calls == []
    assert _count(db, Campaign) == 0 and _count(db, BudgetLedger) == 0


def test_creation_requires_autonomy_level_4(db, product, affiliate_link):
    gateway, adapter = _gateway(db, autonomy_level=3)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.REFUSED_AUTONOMY
    assert adapter.calls == []


def test_max_campaigns_per_execution(db, product, affiliate_link):
    gateway, _ = _gateway(db, max_per_execution=2)

    statuses = [
        gateway.create_campaign_bundle(_request(product, affiliate_link.id)).status
        for _ in range(3)
    ]

    assert statuses == [BundleStatus.CREATED, BundleStatus.CREATED, BundleStatus.STOPPED_LIMIT]
    assert _count(db, Campaign) == 2


def test_abort_on_unreviewed_threshold(db, product, affiliate_link):
    for i in range(3):
        db.add(
            Campaign(
                ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED",
                review_status=CampaignReviewStatus.UNREVIEWED,
            )
        )
    db.flush()
    gateway, adapter = _gateway(db, max_unreviewed=2)

    outcome = gateway.create_campaign_bundle(_request(product, affiliate_link.id))

    assert outcome.status is BundleStatus.ABORTED
    assert adapter.calls == []
    assert _count(db, Alert, Alert.code == "UNREVIEWED_THRESHOLD_EXCEEDED") == 1


def test_budget_refusal_creates_nothing_at_the_provider(db, product, affiliate_link):
    gateway, adapter = _gateway(db)

    # A fatia de exploração é R$30: o 4º lançamento de R$10 não cabe.
    statuses = []
    for _ in range(4):
        gateway._context.campaigns_created = 0  # isola o teto de orçamento do limite/execução
        statuses.append(gateway.create_campaign_bundle(_request(product, affiliate_link.id)).status)

    assert statuses[-1] is BundleStatus.REFUSED_BUDGET
    assert len([c for c in adapter.calls if c[0] == "create_campaign"]) == 3


# ---------- orçamento ----------


def test_budget_counts_commitments_and_actuals(db):
    guard = BudgetGuard(db, PARAMS)
    day = __import__("app.services.budget_guard", fromlist=["today"]).today()

    guard.commit(Decimal("20"), PortfolioTier.EXPLOITATION)
    guard.record_actual(Decimal("30"), PortfolioTier.EXPLOITATION, day=day)

    status = guard.status()
    assert Decimal(status["used"]) == Decimal("50")
    assert guard.check(Decimal("50.01"), PortfolioTier.EXPLOITATION).allowed is False
    assert guard.check(Decimal("20"), PortfolioTier.EXPLOITATION).allowed is True


def test_release_frees_budget(db):
    guard = BudgetGuard(db, PARAMS)
    day = __import__("app.services.budget_guard", fromlist=["today"]).today()
    guard.commit(Decimal("30"), PortfolioTier.EXPLORATION)

    assert guard.check(Decimal("1"), PortfolioTier.EXPLORATION).allowed is False
    guard.release(Decimal("30"), PortfolioTier.EXPLORATION, day=day)

    assert guard.check(Decimal("30"), PortfolioTier.EXPLORATION).allowed is True


def test_budget_never_exceeds_cap_for_random_sequences(db):
    rng = random.Random(7)
    guard = BudgetGuard(db, PARAMS)

    for _ in range(300):
        amount = Decimal(rng.randint(1, 4000)) / 100
        tier = rng.choice(list(PortfolioTier))
        try:
            guard.commit(amount, tier)
        except Exception:  # BudgetExceeded é o caminho esperado
            continue
        assert Decimal(guard.status()["used"]) <= PARAMS.max_daily_ad_spend
        for scope, info in guard.status()["tiers"].items():
            assert Decimal(info["used"]) <= Decimal(info["cap"]), scope


def test_non_positive_amounts_are_refused(db):
    guard = BudgetGuard(db, PARAMS)

    assert guard.check(Decimal("0"), PortfolioTier.EXPLORATION).allowed is False
    assert guard.check(Decimal("-5"), PortfolioTier.EXPLORATION).allowed is False


@pytest.mark.parametrize("seed", range(5))
def test_pure_cap_arithmetic_never_allows_overshoot(seed):
    rng = random.Random(seed)
    cap, used = Decimal("100"), Decimal("0")
    for _ in range(500):
        amount = Decimal(rng.randint(-500, 5000)) / 100
        if budget.can_commit(cap, used, amount):
            used += amount
        assert used <= cap
