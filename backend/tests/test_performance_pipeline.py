"""Pipeline de performance: ingestão -> consolidação -> score."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.ads.mock.adapter import MockAdsAdapter
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.db.session import get_db
from app.domain.enums import ProductState, RunStatus, SettlementStatus
from app.domain.state_machine import transition
from app.main import app
from app.models.ads import Ad, AdSet, Campaign
from app.models.catalog import Product
from app.models.control import WorkflowRun
from app.models.metrics import (
    AdMetricsRaw,
    ConversionRaw,
    PerformanceDaily,
    PerformanceDailyRevision,
)
from app.models.scoring import PerformanceScore
from app.models.tracking import AffiliateLink
from app.services import (
    consolidation_service,
    discovery_service,
    ingestion_service,
    performance_scoring,
    tracking_service,
)
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
TODAY = datetime.now(UTC).date()
SINCE = TODAY - timedelta(days=13)


@pytest.fixture
def advertised(db: Session):
    """Dois produtos em TEST, cada um com link e um anúncio."""
    discovery_service.run_discovery(db, MockAdapter(), limit=2)
    products = db.execute(select(Product).order_by(Product.id).limit(2)).scalars().all()
    for product in products:
        for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
            transition(db, product_id=product.id, to_state=state, reason_code="T", actor="system")
    tracking_service.generate_links(db, MockAdapter(), channel="meta", max_sub_id_length=64)

    for index, product in enumerate(products, start=1):
        link = db.execute(
            select(AffiliateLink).where(AffiliateLink.product_id == product.id)
        ).scalar_one()
        campaign = Campaign(
            ad_account_id="a", name=f"c{index}", objective="o", status="PAUSED",
            external_id=f"t-cmp-{product.id}",
        )
        db.add(campaign)
        db.flush()
        ad_set = AdSet(campaign_id=campaign.id, name="s", status="PAUSED")
        db.add(ad_set)
        db.flush()
        db.add(
            Ad(
                ad_set_id=ad_set.id, product_id=product.id, affiliate_link_id=link.id,
                external_id=f"t-ad-{product.id}", status="PAUSED",
            )
        )
    db.flush()
    return products


def _ingest(db: Session, *, cover: bool = True):
    marketplace = discovery_service.ensure_marketplace(db, MockAdapter())
    ingestion_service.sync_ad_metrics(db, MockAdsAdapter(), since=SINCE, until=TODAY)
    ingestion_service.sync_conversions(
        db, MockAdapter(), marketplace=marketplace, since=SINCE, until=TODAY
    )
    if cover:
        db.add(
            WorkflowRun(
                workflow_name=consolidation_service.SYNC_WORKFLOW,
                dry_run=False,
                status=RunStatus.SUCCESS,
                summary={"window": {"since": SINCE.isoformat(), "until": TODAY.isoformat()}},
            )
        )
        db.flush()


def _count(db, model, *where) -> int:
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


# ---------- ingestão ----------


def test_ad_metrics_raw_is_append_only_across_syncs(db, advertised):
    ingestion_service.sync_ad_metrics(db, MockAdsAdapter(), since=SINCE, until=TODAY)
    first = _count(db, AdMetricsRaw)
    ingestion_service.sync_ad_metrics(db, MockAdsAdapter(), since=SINCE, until=TODAY)

    assert first == 2 * 14
    assert _count(db, AdMetricsRaw) == 2 * first


def test_conversion_sync_is_idempotent_and_keeps_both_sources(db, advertised):
    marketplace = discovery_service.ensure_marketplace(db, MockAdapter())

    def sync():
        return ingestion_service.sync_conversions(
            db, MockAdapter(), marketplace=marketplace, since=SINCE, until=TODAY
        )

    first = sync()
    rows = _count(db, ConversionRaw)
    second = sync()

    assert first.conversions_new > 0 and first.validated_new > 0
    assert second.conversions_new == 0 and second.validated_new == 0
    assert second.conversions_updated == first.conversions_new
    assert _count(db, ConversionRaw) == rows
    assert {s for s in db.execute(select(ConversionRaw.settlement)).scalars()} == {
        SettlementStatus.PROVISIONAL,
        SettlementStatus.SETTLED,
    }


def test_unattributable_conversions_are_stored_but_never_assigned(db, advertised):
    _ingest(db)

    orphan = db.execute(select(ConversionRaw).where(ConversionRaw.sub_id.is_(None))).scalars().all()
    assert orphan  # fica guardada
    result = consolidation_service.consolidate(db, since=SINCE, until=TODAY)
    assert result.unattributed_conversions >= 1
    total = sum(
        (r.revenue or 0)
        for r in db.execute(select(PerformanceDaily)).scalars()
    )
    assert Decimal("9.99") not in {c.commission_value for c in orphan if total == 0}


# ---------- consolidação ----------


def test_without_proven_coverage_revenue_is_unknown_not_zero(db, advertised):
    _ingest(db, cover=False)

    consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    rows = db.execute(select(PerformanceDaily)).scalars().all()
    assert rows
    assert all(r.revenue is None and r.roi is None for r in rows)
    assert all(r.revenue_data_available is False for r in rows)
    assert all(r.cost_data_available is True for r in rows)  # custo veio do Meta


def test_dry_run_sync_does_not_prove_coverage(db):
    db.add(
        WorkflowRun(
            workflow_name=consolidation_service.SYNC_WORKFLOW,
            dry_run=True,
            status=RunStatus.SUCCESS,
            summary={"window": {"since": SINCE.isoformat(), "until": TODAY.isoformat()}},
        )
    )
    db.flush()

    assert consolidation_service.load_coverage(db).conversions == frozenset()


def test_maturity_follows_the_settlement_window(db, advertised):
    _ingest(db)

    consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    by_day = {
        r.metric_date: r.settlement
        for r in db.execute(
            select(PerformanceDaily).where(PerformanceDaily.product_id == advertised[0].id)
        ).scalars()
    }
    old_day = TODAY - timedelta(days=10)
    recent_day = TODAY - timedelta(days=1)
    assert by_day[old_day] is SettlementStatus.SETTLED
    assert by_day[recent_day] is SettlementStatus.PROVISIONAL


def test_settled_day_uses_only_validated_commission_without_fraud(db, advertised):
    _ingest(db)
    product = advertised[0]
    sub_id = db.execute(
        select(AffiliateLink.sub_id).where(AffiliateLink.product_id == product.id)
    ).scalar_one()
    day = TODAY - timedelta(days=10)
    expected = sum(
        (c.commission_value for c in MockAdapter().fetch_validated_conversions(
            since=day, until=day, hint_sub_ids=[sub_id]) if c.sub_id == sub_id),
        Decimal(0),
    )

    consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    row = db.execute(
        select(PerformanceDaily).where(
            PerformanceDaily.product_id == product.id, PerformanceDaily.metric_date == day
        )
    ).scalar_one()
    assert row.revenue == expected
    assert row.revenue_data_available is True


def test_consolidation_is_idempotent(db, advertised):
    _ingest(db)
    first = consolidation_service.consolidate(db, since=SINCE, until=TODAY)
    second = consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    assert first.rows_created > 0
    assert second.rows_created == 0 and second.rows_updated == 0
    assert second.rows_unchanged == first.rows_created
    assert _count(db, PerformanceDailyRevision) == 0


def test_reprocessing_a_changed_day_records_a_revision(db, advertised):
    _ingest(db)
    consolidation_service.consolidate(db, since=SINCE, until=TODAY)
    day = TODAY - timedelta(days=10)
    sub_id = db.execute(
        select(AffiliateLink.sub_id).where(AffiliateLink.product_id == advertised[0].id)
    ).scalar_one()
    marketplace = discovery_service.ensure_marketplace(db, MockAdapter())
    # Chega uma liquidação nova para um dia que já estava consolidado.
    db.add(
        ConversionRaw(
            marketplace_id=marketplace.id,
            source=ingestion_service.SOURCE_VALIDATED,
            external_order_id="late-settlement",
            sub_id=sub_id,
            conversion_date=day,
            commission_value=Decimal("5.00"),
            status="COMPLETED",
            fraud_status="VERIFIED",
            settlement=SettlementStatus.SETTLED,
            payload={},
        )
    )
    db.flush()

    result = consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    assert result.revisions == 1
    revision = db.execute(select(PerformanceDailyRevision)).scalar_one()
    assert revision.previous_values["revenue"] != revision.new_values["revenue"]


# ---------- score ----------


def test_scores_are_written_once_and_not_repeated(db, advertised):
    _ingest(db)
    consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    first = performance_scoring.run_performance_scoring(db, PARAMS)
    second = performance_scoring.run_performance_scoring(db, PARAMS)

    assert first.scored > 0
    assert second.scored == 0 and second.unchanged == first.scored
    assert _count(db, PerformanceScore) == first.scored


def test_score_without_revenue_is_indicative_and_flags_missing_roi(db, advertised):
    _ingest(db, cover=False)
    consolidation_service.consolidate(db, since=SINCE, until=TODAY)

    performance_scoring.run_performance_scoring(db, PARAMS)

    scores = db.execute(select(PerformanceScore)).scalars().all()
    assert scores
    assert all(s.data_available is False for s in scores)
    assert all(s.components["roi"]["available"] is False for s in scores)


# ---------- endpoints ----------


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "troque-esta-chave"}


def test_full_pipeline_through_the_endpoints(client, db, advertised):
    sync = client.post("/api/v1/trigger/performance/sync?dry_run=false", headers=HEADERS)
    assert sync.status_code == 200, sync.text
    assert sync.json()["summary"]["ad_metric_rows"] == 2 * 14

    consolidate = client.post(
        "/api/v1/trigger/performance/consolidate?dry_run=false", headers=HEADERS
    )
    assert consolidate.status_code == 200, consolidate.text
    assert consolidate.json()["summary"]["daily"]["rows_created"] > 0
    assert consolidate.json()["summary"]["scores"]["scored"] > 0

    daily = client.get(
        f"/api/v1/performance/daily?product_id={advertised[0].id}", headers=HEADERS
    ).json()
    assert daily["items"]
    assert all(item["revenue_data_available"] for item in daily["items"])

    summary = client.get("/api/v1/performance/summary?days=14", headers=HEADERS).json()
    assert summary["measured_rows"] > 0
    assert summary["roi"] is not None


def test_dry_run_pipeline_persists_no_facts(client, db, advertised):
    client.post("/api/v1/trigger/performance/sync?dry_run=true", headers=HEADERS)

    assert _count(db, AdMetricsRaw) == 0
    assert _count(db, ConversionRaw) == 0


def test_summary_has_null_roi_when_nothing_measured(client):
    summary = client.get("/api/v1/performance/summary", headers=HEADERS).json()

    assert summary["roi"] is None and summary["ad_spend"] is None
