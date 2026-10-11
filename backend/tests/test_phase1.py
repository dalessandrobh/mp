from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.adapters.marketplace.base import MarketplaceProduct, SortBy
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.domain.enums import ProductState
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.scoring import OpportunityScore
from app.services.discovery_service import run_discovery
from app.services.opportunity_scoring import compute_opportunity_score
from app.services.qualification_service import run_qualification

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def _p(**kw) -> MarketplaceProduct:
    base = dict(
        external_product_id="x",
        title="t",
        product_url="u",
        commission_rate=Decimal("0.10"),
        sales=500,
        rating=Decimal("4.8"),
        commission_value=Decimal("10"),
        discount_rate=20,
        shop_types=(1,),
        period_end=NOW + timedelta(days=60),
    )
    base.update(kw)
    return MarketplaceProduct(**base)


# ---------- score ----------


def test_score_is_within_bounds_and_available():
    r = compute_opportunity_score(_p(), now=NOW)
    assert 0 <= r.score <= 100
    assert r.data_available and r.missing_fields == []


def test_missing_sales_makes_score_indicative_not_zero():
    r = compute_opportunity_score(_p(sales=None), now=NOW)
    assert r.data_available is False
    assert "sales" in r.missing_fields
    assert r.components["sales"] is None
    assert r.score > 0  # renormaliza sobre o que existe


def test_better_commission_scores_higher():
    low = compute_opportunity_score(_p(commission_rate=Decimal("0.02")), now=NOW)
    high = compute_opportunity_score(_p(commission_rate=Decimal("0.15")), now=NOW)
    assert high.score > low.score


def test_expired_offer_time_component_is_zero():
    r = compute_opportunity_score(_p(period_end=NOW - timedelta(days=1)), now=NOW)
    assert r.components["time"] == 0.0


# ---------- mock adapter ----------


def test_mock_is_deterministic_and_paginates():
    a, b = MockAdapter(seed=1, now=NOW), MockAdapter(seed=1, now=NOW)
    assert a.search_products(limit=5).items == b.search_products(limit=5).items
    page = a.search_products(page=1, limit=10)
    assert len(page.items) == 10 and page.has_next_page


def test_mock_sorts_by_commission():
    items = MockAdapter(now=NOW).search_products(sort_by=SortBy.COMMISSION, limit=40).items
    rates = [i.commission_rate for i in items]
    assert rates == sorted(rates, reverse=True)


# ---------- discovery ----------


def test_discovery_creates_products_in_discovery_state(db):
    r = run_discovery(db, MockAdapter(now=NOW), limit=10)
    assert r.seen == r.new_products == 10
    states = set(db.execute(select(ProductCurrentState.state)).scalars())
    assert states == {ProductState.DISCOVERY}


def test_discovery_is_idempotent_for_products_but_appends_snapshots(db):
    adapter = MockAdapter(now=NOW)
    run_discovery(db, adapter, limit=10)
    second = run_discovery(db, adapter, limit=10)
    assert second.new_products == 0
    assert db.scalar(select(func.count()).select_from(Product)) == 10
    assert db.scalar(select(func.count()).select_from(ProductSnapshot)) == 20


def test_snapshot_marks_missing_fields_as_unavailable(db):
    run_discovery(db, MockAdapter(now=NOW), limit=40)
    sparse = db.execute(
        select(ProductSnapshot).where(ProductSnapshot.sales_volume.is_(None)).limit(1)
    ).scalar_one()
    assert sparse.data_available["sales_volume"] is False
    assert sparse.rating is None  # ausente, não zero


# ---------- qualification ----------


def test_qualification_moves_every_product_and_scores_it(db):
    run_discovery(db, MockAdapter(now=datetime.now(UTC)), limit=40)
    r = run_qualification(db)
    assert r.evaluated == 40
    assert db.scalar(select(func.count()).select_from(OpportunityScore)) == 40
    accounted = len(r.candidates) + len(r.rejected) + len(r.expired) + len(r.waiting_data)
    assert accounted == 40


def test_missing_data_waits_instead_of_rejecting(db):
    run_discovery(db, MockAdapter(now=datetime.now(UTC)), limit=40)
    r = run_qualification(db)
    assert r.waiting_data, "mock tem produtos sem vendas"
    for pid in r.waiting_data:
        state = db.get(ProductCurrentState, pid).state
        assert state is ProductState.QUALIFICATION


def test_candidates_pass_the_rules_and_transitions_are_audited(db):
    run_discovery(db, MockAdapter(now=datetime.now(UTC)), limit=40)
    r = run_qualification(db)
    assert r.candidates
    pid = r.candidates[0]
    chain = [
        t.to_state
        for t in db.execute(
            select(ProductStateTransition)
            .where(ProductStateTransition.product_id == pid)
            .order_by(ProductStateTransition.id)
        ).scalars()
    ]
    assert chain == [ProductState.DISCOVERY, ProductState.QUALIFICATION, ProductState.CANDIDATE]


def test_qualification_is_rerunnable(db):
    run_discovery(db, MockAdapter(now=datetime.now(UTC)), limit=40)
    run_qualification(db)
    again = run_qualification(db)
    # só quem esperava dado volta a ser avaliado; ninguém ilegal é movido
    assert again.candidates == [] and again.rejected == [] and again.expired == []
