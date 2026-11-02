from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import CampaignReviewStatus, PortfolioTier, RunStatus, SettlementStatus
from app.main import app
from app.models.ads import Campaign
from app.models.control import Alert, WorkflowRun
from app.models.metrics import PerformanceDaily
from app.models.portfolio import PortfolioProduct, PortfolioSnapshot
from app.services import alert_rules, consolidation_service
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
TODAY = datetime.now(UTC).date()


def _codes(result) -> set[str]:
    return {a["code"] for a in result.created}


def _fresh_sync(db):
    db.add(
        WorkflowRun(
            workflow_name=consolidation_service.SYNC_WORKFLOW, dry_run=False,
            status=RunStatus.SUCCESS, finished_at=datetime.now(UTC),
        )
    )
    db.flush()


def _roi_rows(db, product_id, rois, *, last_day_offset=1):
    for i, roi in enumerate(rois):
        db.add(
            PerformanceDaily(
                metric_date=TODAY - timedelta(days=last_day_offset + i), product_id=product_id,
                channel="meta", roi=Decimal(roi), revenue_data_available=True,
                cost_data_available=True, settlement=SettlementStatus.PROVISIONAL,
            )
        )
    db.flush()


def test_quiet_system_raises_nothing(db):
    assert alert_rules.evaluate(db, PARAMS, max_unreviewed=10).created == []


def test_unreviewed_queue_over_the_limit_is_critical(db):
    for i in range(3):
        db.add(
            Campaign(ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED",
                     review_status=CampaignReviewStatus.UNREVIEWED)
        )
    db.flush()

    result = alert_rules.evaluate(db, PARAMS, max_unreviewed=2)

    assert [a["severity"] for a in result.created] == ["CRITICAL"]
    assert _codes(result) == {"UNREVIEWED_QUEUE_FULL"}


def test_budget_near_the_cap_warns_but_not_before(db):
    guard = BudgetGuard(db, PARAMS)
    guard.commit(Decimal("20"), PortfolioTier.EXPLORATION)
    assert alert_rules.evaluate(db, PARAMS, max_unreviewed=10).created == []

    guard.commit(Decimal("70"), PortfolioTier.EXPLOITATION)  # 90% do teto

    assert _codes(alert_rules.evaluate(db, PARAMS, max_unreviewed=10)) == {"BUDGET_NEAR_CAP"}


def test_three_negative_days_alert_without_pausing_anything(db, product):
    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    _fresh_sync(db)
    _roi_rows(db, product.id, ["-0.2", "-0.5", "-0.1"])

    result = alert_rules.evaluate(db, PARAMS, max_unreviewed=10)

    assert _codes(result) == {"ROI_NEGATIVE_3D"}
    assert "Nada foi pausado" in result.created[0]["message"]


@pytest.mark.parametrize(
    "rois, offset",
    [
        (["-0.2", "0.1", "-0.1"], 1),   # um dia positivo no meio
        (["-0.2", "-0.5"], 1),          # só 2 dias
        (["-0.2", "-0.5", "-0.1"], 6),  # sequência antiga, não é "agora"
    ],
)
def test_negative_roi_rule_needs_three_recent_consecutive_days(db, product, rois, offset):
    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    _fresh_sync(db)
    _roi_rows(db, product.id, rois, last_day_offset=offset)

    assert "ROI_NEGATIVE_3D" not in _codes(alert_rules.evaluate(db, PARAMS, max_unreviewed=10))


def test_stale_performance_data_alerts_only_when_there_is_a_portfolio(db, product):
    assert alert_rules.evaluate(db, PARAMS, max_unreviewed=10).created == []

    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    db.flush()

    assert _codes(alert_rules.evaluate(db, PARAMS, max_unreviewed=10)) == {
        "PERFORMANCE_DATA_STALE"
    }


def test_dry_run_sync_does_not_count_as_fresh_data(db, product):
    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    db.add(
        WorkflowRun(
            workflow_name=consolidation_service.SYNC_WORKFLOW, dry_run=True,
            status=RunStatus.SUCCESS, finished_at=datetime.now(UTC),
        )
    )
    db.flush()

    assert "PERFORMANCE_DATA_STALE" in _codes(alert_rules.evaluate(db, PARAMS, max_unreviewed=10))


def test_same_alert_is_not_raised_again_within_24h(db):
    for i in range(3):
        db.add(Campaign(ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED"))
    db.flush()

    first = alert_rules.evaluate(db, PARAMS, max_unreviewed=2)
    second = alert_rules.evaluate(db, PARAMS, max_unreviewed=2)

    assert len(first.created) == 1
    assert second.created == [] and second.skipped_duplicates == 1


def test_alert_raised_long_ago_is_raised_again(db):
    for i in range(3):
        db.add(Campaign(ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED"))
    db.flush()
    alert_rules.evaluate(db, PARAMS, max_unreviewed=2)
    for alert in db.execute(select(Alert)).scalars():
        alert.created_at = datetime.now(UTC) - timedelta(hours=30)
    db.flush()

    again = alert_rules.evaluate(db, PARAMS, max_unreviewed=2)

    assert len(again.created) == 1


# ---------- endpoints ----------


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


KEY = {"X-API-Key": "troque-esta-chave"}


def _jwt() -> dict:
    token = jwt.encode({"email": "ana@x.com"}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _enough_unreviewed(db):
    for i in range(11):
        db.add(Campaign(ad_account_id="a", name=f"c{i}", objective="o", status="PAUSED"))
    db.flush()


def test_evaluate_endpoint_returns_only_new_alerts_in_items(client, db):
    _enough_unreviewed(db)

    first = client.post("/api/v1/trigger/alerts/evaluate?dry_run=false", headers=KEY).json()
    second = client.post("/api/v1/trigger/alerts/evaluate?dry_run=false", headers=KEY).json()

    assert first["summary"]["created"] == 1 and first["items"][0]["severity"] == "CRITICAL"
    assert second["summary"]["created"] == 0 and second["items"] == []


def test_evaluate_dry_run_reports_but_persists_no_alert(client, db):
    _enough_unreviewed(db)

    body = client.post("/api/v1/trigger/alerts/evaluate?dry_run=true", headers=KEY).json()

    assert body["summary"]["created"] == 1
    assert db.execute(select(func.count()).select_from(Alert)).scalar_one() == 0


def test_alerts_listing_and_acknowledge(client, db):
    _enough_unreviewed(db)
    client.post("/api/v1/trigger/alerts/evaluate?dry_run=false", headers=KEY)

    listed = client.get("/api/v1/alerts", headers=KEY).json()["items"]
    assert len(listed) == 1
    anonymous = client.post(f"/api/v1/alerts/{listed[0]['id']}/acknowledge", headers=KEY)
    assert anonymous.status_code == 401

    done = client.post(f"/api/v1/alerts/{listed[0]['id']}/acknowledge", headers=_jwt())

    assert done.json()["acknowledged_by"] == "human:ana@x.com"
    assert client.get("/api/v1/alerts", headers=KEY).json()["items"] == []
    everything = client.get("/api/v1/alerts?include_acknowledged=true", headers=KEY).json()
    assert len(everything["items"]) == 1


def test_snapshot_endpoint_records_the_day_and_overwrites_on_repeat(client, db, product):
    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION,
                            allocated_daily_budget=Decimal("10")))
    db.flush()

    first = client.post("/api/v1/trigger/portfolio/snapshot?dry_run=false", headers=KEY).json()
    second = client.post("/api/v1/trigger/portfolio/snapshot?dry_run=false", headers=KEY).json()

    assert first["summary"]["active_count"] == 1
    assert second["summary"]["total_daily_budget"] == "10.00"
    assert db.execute(select(func.count()).select_from(PortfolioSnapshot)).scalar_one() == 1


# ---------- revisão de campanhas ----------


def _campaign(db, **overrides):
    campaign = Campaign(ad_account_id="a", name="c", objective="o", status="PAUSED", **overrides)
    db.add(campaign)
    db.flush()
    return campaign


def test_campaign_review_clears_the_unreviewed_queue_and_never_touches_status(client, db):
    campaign = _campaign(db)

    listed = client.get("/api/v1/campaigns?review_status=UNREVIEWED", headers=KEY).json()
    assert [c["id"] for c in listed["items"]] == [campaign.id]

    done = client.post(
        f"/api/v1/campaigns/{campaign.id}/review", headers=_jwt(), json={"decision": "APPROVED"}
    )

    assert done.json()["review_status"] == "APPROVED"
    db.refresh(campaign)
    assert campaign.status == "PAUSED" and campaign.reviewed_by == "human:ana@x.com"
    again = client.get("/api/v1/campaigns?review_status=UNREVIEWED", headers=KEY).json()
    assert again["items"] == []


def test_campaign_review_needs_a_human_and_only_works_once(client, db):
    campaign = _campaign(db)
    url = f"/api/v1/campaigns/{campaign.id}/review"

    assert client.post(url, headers=KEY, json={"decision": "APPROVED"}).status_code == 401
    assert client.post(url, headers=_jwt(), json={"decision": "ACTIVE"}).status_code == 422
    assert client.post(url, headers=_jwt(), json={"decision": "REJECTED"}).status_code == 200
    assert client.post(url, headers=_jwt(), json={"decision": "APPROVED"}).status_code == 400


def test_reviewing_below_the_limit_lets_the_gateway_create_again(db):
    for _ in range(3):
        _campaign(db, review_status=CampaignReviewStatus.UNREVIEWED)
    assert alert_rules.evaluate(db, PARAMS, max_unreviewed=2).created  # fila cheia

    for c in db.execute(select(Campaign)).scalars():
        c.review_status = CampaignReviewStatus.APPROVED
    db.flush()

    later = datetime.now(UTC) + timedelta(days=2)  # fora da janela de deduplicação
    assert "UNREVIEWED_QUEUE_FULL" not in _codes(
        alert_rules.evaluate(db, PARAMS, max_unreviewed=2, now=later)
    )
