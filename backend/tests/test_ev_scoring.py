"""EV no serviço: monta as entradas, grava append-only e passa a decidir quem entra."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import ProductOffer
from app.domain.enums import ProductState, SettlementStatus
from app.domain.state_machine import transition
from app.models.catalog import Marketplace, Product, ProductSnapshot
from app.models.metrics import PerformanceDaily
from app.models.scoring import ExpectedValue
from app.services import discovery_service, ev_scoring
from app.services.portfolio_service import PortfolioParams

TODAY = datetime.now(UTC).date()
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
# `_persist` já põe o produto novo em DISCOVERY pela state machine.
CHAIN = (ProductState.QUALIFICATION,)


def _product(db: Session, marketplace: Marketplace, ext: str, **snapshot) -> Product:
    offer = ProductOffer(
        external_product_id=ext,
        title=f"Produto {ext}",
        product_url=f"https://example.test/{ext}",
        category_path=(snapshot.pop("category", "100630"),),
        price=snapshot.pop("price", Decimal("150.00")),
        commission_rate=snapshot.pop("rate", Decimal("0.20")),
        sales_volume=snapshot.pop("sales", 1000),
        rating=snapshot.pop("rating", Decimal("4.6")),
        # O marketplace do fixture não declara campo não suportado, então o Opportunity
        # Score só é decisório com todos os componentes presentes.
        rating_count=snapshot.pop("rating_count", 500),
        stock=snapshot.pop("stock", 50),
    )
    discovery_service._persist(db, marketplace, [offer], datetime.now(UTC))
    product = db.execute(
        select(Product).where(Product.external_product_id == ext)
    ).scalar_one()
    for state in CHAIN:
        transition(db, product_id=product.id, to_state=state, reason_code="T", actor="system")
    db.flush()
    return product


def _entries(db: Session) -> list:
    """Recomendações de entrada no portfólio, na ordem em que foram criadas."""
    from app.models.ai import AiRecommendation

    rows = db.execute(
        select(AiRecommendation).order_by(AiRecommendation.id)
    ).scalars().all()
    return [r for r in rows if (r.rationale or {}).get("action") == "ENTER_PORTFOLIO"]


def _traffic(db: Session, product: Product, *, clicks: int, conversions: int, channel="ig"):
    db.add(
        PerformanceDaily(
            metric_date=TODAY,
            product_id=product.id,
            channel=channel,
            clicks=clicks,
            conversions=conversions,
            revenue_data_available=True,
            settlement=SettlementStatus.PROVISIONAL,
        )
    )
    db.flush()


def test_it_scores_the_products_that_dispute_a_slot(db: Session, marketplace):
    _product(db, marketplace, "a")
    _product(db, marketplace, "b")

    result = ev_scoring.run_ev_scoring(db)

    assert result.scored == 2 and result.with_own_data == 0
    rows = db.execute(select(ExpectedValue)).scalars().all()
    assert len(rows) == 2
    assert all(r.algorithm_version == "ev_v1" and not r.data_available for r in rows)


def test_the_commission_in_the_row_is_the_one_the_api_reported(db: Session, marketplace):
    _product(db, marketplace, "a", price=Decimal("136.00"), rate=Decimal("0.25"))

    ev_scoring.run_ev_scoring(db)

    row = db.execute(select(ExpectedValue)).scalar_one()
    assert row.commission_value == Decimal("34.00")
    assert row.ev_per_click == (row.commission_value * row.cvr_estimate).quantize(
        Decimal("0.000001")
    )


def test_measured_clicks_and_sales_become_the_evidence(db: Session, marketplace):
    product = _product(db, marketplace, "a")
    _traffic(db, product, clicks=400, conversions=20)

    result = ev_scoring.run_ev_scoring(db)

    row = db.execute(select(ExpectedValue)).scalar_one()
    assert result.with_own_data == 1 and row.data_available
    assert row.clicks == 400 and row.conversions == 20
    assert row.alpha > Decimal("20") and row.beta > Decimal("300")


def test_a_product_without_commission_is_skipped_not_scored_as_zero(db: Session, marketplace):
    _product(db, marketplace, "a", price=None)

    result = ev_scoring.run_ev_scoring(db)

    assert result.scored == 0 and result.skipped_no_commission == 1
    assert db.execute(select(ExpectedValue)).first() is None


def test_the_snapshot_series_feeds_the_momentum(db: Session, marketplace):
    product = _product(db, marketplace, "a", sales=1000)
    # Série com dias de verdade: a aceleração sai dela, não de "um dia".
    for days_ago, sales in ((6, 800), (4, 900), (2, 1000)):
        db.add(
            ProductSnapshot(
                product_id=product.id,
                price=Decimal("150.00"),
                commission_rate=Decimal("0.20"),
                commission_value=Decimal("30.00"),
                sales_volume=sales,
                rating=Decimal("4.6"),
                captured_at=datetime.now(UTC) - timedelta(days=days_ago),
                data_available={},
            )
        )
    db.flush()

    result = ev_scoring.run_ev_scoring(db)

    row = db.execute(select(ExpectedValue)).scalar_one()
    assert result.with_momentum == 1
    assert row.momentum is not None and row.momentum > 0
    assert row.components["prior_factors"]["momentum"]["value"] != "1"


def test_the_table_is_append_only(db: Session, marketplace):
    _product(db, marketplace, "a")
    ev_scoring.run_ev_scoring(db)
    row = db.execute(select(ExpectedValue)).scalar_one()

    with pytest.raises(Exception, match="append-only"):
        db.execute(ExpectedValue.__table__.delete().where(ExpectedValue.id == row.id))


def test_every_run_appends_instead_of_rewriting(db: Session, marketplace):
    _product(db, marketplace, "a")

    ev_scoring.run_ev_scoring(db)
    ev_scoring.run_ev_scoring(db)

    assert len(db.execute(select(ExpectedValue)).scalars().all()) == 2


# ------------------------------------------------------- prior da categoria


def test_a_category_without_enough_sample_keeps_the_global_prior(db: Session, marketplace):
    product = _product(db, marketplace, "a")
    _traffic(db, product, clicks=1000, conversions=50)

    result = ev_scoring.run_ev_scoring(db)

    assert result.category_priors == 0, "um produto não faz prior de categoria"
    row = db.execute(select(ExpectedValue)).scalar_one()
    assert row.prior_source == "global"


def test_a_category_with_sample_becomes_the_prior(db: Session, marketplace):
    """Pooling parcial: a categoria só assume quando tem amostra para isso."""
    for i in range(6):
        product = _product(db, marketplace, f"p{i}", category="100630")
        # Taxas próximas entre si: categoria homogênea gera prior forte.
        _traffic(db, product, clicks=500, conversions=20 + i)

    result = ev_scoring.run_ev_scoring(db)

    assert result.category_priors == 1
    rows = db.execute(select(ExpectedValue)).scalars().all()
    assert all(r.prior_source == "categoria 100630" for r in rows)


def test_the_latest_ev_per_product_is_what_the_readers_get(db: Session, marketplace):
    product = _product(db, marketplace, "a")
    ev_scoring.run_ev_scoring(db)
    _traffic(db, product, clicks=1000, conversions=100)
    ev_scoring.run_ev_scoring(db)

    latest = ev_scoring.latest_evs(db)
    assert latest[product.id].clicks == 1000
    assert ev_scoring.latest_ev(db, product.id).clicks == 1000


# ------------------------------------------------------- quem entra no portfólio


def test_the_candidate_with_the_best_ev_enters_first(db: Session, marketplace):
    """O ponto de todo o trabalho: a vaga vai para quem rende mais, não para o mais
    popular. `opp_v2` satura a comissão em R$ 30 e empataria os dois."""
    from app.services import decision_engine, opportunity_scoring

    barato = _product(
        db, marketplace, "barato", price=Decimal("22.00"), rate=Decimal("0.08"), sales=90000
    )
    caro = _product(
        db, marketplace, "caro", price=Decimal("136.00"), rate=Decimal("0.25"), sales=14000
    )
    opportunity_scoring.run_opportunity_scoring(db)
    for product in (barato, caro):
        transition(
            db, product_id=product.id, to_state=ProductState.CANDIDATE,
            reason_code="T", actor="system",
        )
    ev_scoring.run_ev_scoring(db)

    decision_engine.analyze(db, PARAMS)

    entries = _entries(db)
    assert entries, "havia vaga de exploração e dois candidatos"
    first = entries[0]
    assert first.subject_id == str(caro.id)
    assert "receita esperada por clique" in first.rationale["why"]
    assert first.rationale["data_used"]["ev_has_own_clicks"] is False


def test_without_ev_the_decision_falls_back_to_the_opportunity_score(db: Session, marketplace):
    """Nunca se deixa de decidir por falta de um número novo."""
    from app.services import decision_engine, opportunity_scoring

    _product(db, marketplace, "a")
    opportunity_scoring.run_opportunity_scoring(db)
    product = db.execute(select(Product)).scalar_one()
    transition(
        db, product_id=product.id, to_state=ProductState.CANDIDATE,
        reason_code="T", actor="system",
    )

    decision_engine.analyze(db, PARAMS)

    entries = _entries(db)
    assert len(entries) == 1
    assert "sem EV calculado" in entries[0].rationale["why"]
    assert "ev_per_click" not in entries[0].rationale["data_used"]


def test_the_trigger_endpoint_scores(db: Session, marketplace):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    _product(db, marketplace, "a")
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(
            "/api/v1/trigger/scoring/ev?dry_run=false",
            headers={"X-API-Key": "troque-esta-chave"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["summary"]["scored"] == 1
