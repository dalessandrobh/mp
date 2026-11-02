from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import Settings
from app.db.session import get_db
from app.domain.enums import DecisionType, PortfolioTier, RunStatus
from app.main import app
from app.models.ai import AiRecommendation
from app.models.control import Alert, WorkflowRun
from app.models.metrics import ConversionRaw
from app.models.portfolio import PortfolioProduct
from app.services import (
    consolidation_service,
    daily_report,
    discovery_service,
    opportunity_scoring,
    qualification_service,
    tracking_service,
)
from app.services.portfolio_service import PortfolioParams

TZ = ZoneInfo("America/Sao_Paulo")
PARAMS = PortfolioParams(
    max_daily_ad_spend=Decimal("100"), min_daily_test_budget=Decimal("10"),
    exploration_percentage=30, min_active_products=3, max_active_products=15,
    min_clicks_for_decision=50, min_impressions_for_decision=1000, min_test_duration_days=3,
)
KEY = {"X-API-Key": "troque-esta-chave"}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, dry_run=False, **overrides)


def _build(db, **kwargs):
    return daily_report.build(db, _settings(mock_marketplace=False, shopee_app_id="1",
                                            shopee_secret="s", ai_autonomy_level=2),
                              PARAMS, **kwargs)


@pytest.fixture
def funnel(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


def test_a_quiet_day_says_so_instead_of_inventing_activity(db):
    report = _build(db)

    assert "nada novo no funil" in report.message
    assert "nenhum pedido hoje" in report.message
    assert "nada — está tudo em dia" in report.message
    assert "funil vazio" in report.message


def test_the_funnel_section_counts_discoveries_rejections_and_reasons(db, funnel):
    message = _build(db).message

    assert "40 produtos novos" in message and "qualificados" in message
    assert "rejeitados (" in message and "sem estoque" in message
    assert "viraram candidatos" in message


def test_the_header_states_the_mode_and_warns_when_nothing_is_being_saved(db):
    live = _build(db).message
    readonly = daily_report.build(
        db, Settings(_env_file=None, dry_run=True), PARAMS
    ).message

    assert "Shopee real · anúncios desligados · autonomia 2" in live
    assert "SOMENTE LEITURA" not in live
    assert "SOMENTE LEITURA" in readonly and "mock" in readonly


def test_changes_name_the_product_and_who_decided(db, funnel):
    from sqlalchemy import select

    from app.domain.enums import ProductState
    from app.domain.state_machine import transition
    from app.models.catalog import Product
    from app.models.funnel import ProductCurrentState

    candidate = db.execute(
        select(Product).join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .where(ProductCurrentState.state == ProductState.CANDIDATE).limit(1)
    ).scalar_one()
    transition(
        db, product_id=candidate.id, to_state=ProductState.TEST,
        reason_code="PORTFOLIO_ENTRY", actor="human:ana@x.com",
    )

    message = _build(db).message

    assert f"{candidate.title} → em teste (você)" in message


def test_pending_recommendations_and_critical_alerts_are_what_waits_for_you(db):
    db.add(AiRecommendation(decision_type=DecisionType.PROMOTE, subject_type="product",
                            subject_id="1", rationale={"what": "colocar X em teste"}))
    db.add(Alert(severity="CRITICAL", code="UNREVIEWED_QUEUE_FULL", message="m"))
    db.flush()

    message = _build(db).message

    assert "1 recomendação em Inteligência: colocar X em teste" in message
    assert "1 alerta(s) crítico(s): UNREVIEWED_QUEUE_FULL" in message
    assert "alertas abertos: 1" in message


def _conversion(db, marketplace, *, sub_id, status="COMPLETED", commission="12.50", day=None,
                order="O1", fraud="VERIFIED"):
    db.add(ConversionRaw(
        marketplace_id=marketplace.id, source="conversion_report", external_order_id=order,
        sub_id=sub_id, conversion_date=day or datetime.now(TZ).date(),
        commission_value=Decimal(commission), status=status, fraud_status=fraud, payload={},
    ))
    db.flush()


def test_sales_separate_completed_from_pending_and_call_the_pending_part_an_estimate(db, funnel):
    from sqlalchemy import select

    from app.models.catalog import Marketplace

    mp = db.execute(select(Marketplace)).scalars().first()
    _conversion(db, mp, sub_id=None, order="A", commission="10.00")
    _conversion(db, mp, sub_id=None, order="B", status="PENDING", commission="5.50")
    _conversion(db, mp, sub_id=None, order="C", status="CANCELLED", commission="99.00")
    _conversion(db, mp, sub_id=None, order="D", commission="77.00", fraud="FRAUD")

    sales = _build(db)
    text = sales.message

    assert sales.data["sales"]["orders"] == 3  # a fraude não conta
    assert "R$ 10,00 concluída + R$ 5,50 pendente" in text
    assert "estimativa, não liquidado" in text
    assert "3 sem identificação de produto" in text
    assert "99" not in text  # cancelado não entra na comissão


def test_sales_are_attributed_to_the_product_through_the_sub_id(db, funnel):
    from sqlalchemy import select

    from app.domain.enums import ProductState
    from app.domain.state_machine import transition
    from app.models.catalog import Marketplace, Product
    from app.models.funnel import ProductCurrentState
    from app.models.tracking import AffiliateLink

    product = db.execute(
        select(Product).join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .where(ProductCurrentState.state == ProductState.CANDIDATE).limit(1)
    ).scalar_one()
    transition(
        db, product_id=product.id, to_state=ProductState.TEST, reason_code="T", actor="system"
    )
    tracking_service.generate_links(db, MockAdapter(), channel="meta", max_sub_id_length=48)
    link = db.execute(
        select(AffiliateLink).where(AffiliateLink.product_id == product.id)
    ).scalar_one()
    marketplace = db.get(Marketplace, product.marketplace_id)
    _conversion(db, marketplace, sub_id=link.sub_id, commission="30.00")

    sales = _build(db).data["sales"]

    assert sales["unattributed"] == 0
    assert sales["top_products"][0] == {"product": product.title, "commission": "30.00"}


def test_yesterdays_sales_do_not_leak_into_today(db, funnel):
    from sqlalchemy import select

    from app.models.catalog import Marketplace

    mp = db.execute(select(Marketplace)).scalars().first()
    _conversion(db, mp, sub_id=None, day=datetime.now(TZ).date() - timedelta(days=1))

    assert "nenhum pedido hoje" in _build(db).message


def test_the_day_is_the_brazilian_day(db):
    day = datetime(2026, 9, 6).date()
    start, end = daily_report.day_bounds(day)

    # 06/09 00:00 em Brasília (UTC-3) = 03:00 UTC; o dia tem 24h.
    assert start == datetime(2026, 9, 6, 3, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=24)


def test_stale_performance_data_is_flagged_only_when_there_is_a_portfolio(db, product):
    assert "⚠️" not in _build(db).message.split("*Saúde*")[1]

    db.add(PortfolioProduct(product_id=product.id, tier=PortfolioTier.EXPLORATION))
    db.add(WorkflowRun(workflow_name=consolidation_service.SYNC_WORKFLOW, dry_run=False,
                       status=RunStatus.SUCCESS,
                       finished_at=datetime.now(UTC) - timedelta(hours=20)))
    db.flush()

    assert "há 20h ⚠️" in _build(db).message


def test_failed_runs_of_the_day_are_listed(db):
    db.add(WorkflowRun(workflow_name="ads_creation", dry_run=False, status=RunStatus.ABORTED))
    db.flush()

    assert "falhas hoje: 1 (ads_creation)" in _build(db).message


def test_the_message_fits_a_whatsapp_message_even_on_a_busy_day(db, funnel):
    from sqlalchemy import select

    from app.domain.enums import ProductState
    from app.domain.state_machine import transition
    from app.models.catalog import Product
    from app.models.funnel import ProductCurrentState

    ids = db.execute(
        select(Product.id).join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
        .where(ProductCurrentState.state == ProductState.CANDIDATE)
    ).scalars().all()
    for pid in ids:
        transition(db, product_id=pid, to_state=ProductState.TEST, reason_code="T", actor="system")

    message = _build(db).message

    assert len(message) < 3500 and "… e mais" in message


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_trigger_returns_the_ready_message_for_n8n(client, funnel):
    body = client.post("/api/v1/trigger/report/daily?dry_run=false", headers=KEY).json()

    assert body["status"] == "SUCCESS"
    assert body["summary"]["message"].startswith("📊 *MP — resumo de")
    assert body["summary"]["funnel_total"]


def test_the_report_is_read_only(client, db, funnel):
    from sqlalchemy import func, select

    from app.models.funnel import ProductStateTransition

    before = db.execute(select(func.count()).select_from(ProductStateTransition)).scalar_one()

    client.post("/api/v1/trigger/report/daily?dry_run=false", headers=KEY)
    client.get("/api/v1/report/daily", headers=KEY)

    after = db.execute(select(func.count()).select_from(ProductStateTransition)).scalar_one()
    assert after == before


def test_the_read_endpoint_accepts_a_day_and_rejects_garbage(client):
    assert client.get("/api/v1/report/daily?day=2026-09-06", headers=KEY).status_code == 200
    assert client.get("/api/v1/report/daily?day=ontem", headers=KEY).status_code == 400
    assert client.get("/api/v1/report/daily").status_code == 401
    assert client.post("/api/v1/trigger/report/daily").status_code == 401
