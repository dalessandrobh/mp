"""Guarda de réplica na ENTRADA do portfólio: vaga de teste só para o que se pode divulgar."""

import dataclasses

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.domain import brand_risk
from app.domain.enums import DecisionType
from app.main import app
from app.models.ai import AiRecommendation
from app.models.catalog import Product
from app.services import (
    decision_engine,
    discovery_service,
    opportunity_scoring,
    qualification_service,
    risk_service,
)
from tests.test_category_quota import PARAMS


@pytest.fixture
def candidates(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=500)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)
    opportunity_scoring.run_promotion(db)


def _entering(db) -> list[int]:
    recs = db.execute(
        select(AiRecommendation).where(AiRecommendation.decision_type == DecisionType.PROMOTE)
    ).scalars()
    return [int(r.subject_id) for r in recs if r.rationale.get("action") == "ENTER_PORTFOLIO"]


def _verdict(blocked: bool) -> brand_risk.RiskVerdict:
    return brand_risk.RiskVerdict(blocked, "RISK_TEST" if blocked else "OK", "teste")


def test_a_blocked_candidate_never_takes_a_test_slot(db: Session, candidates):
    params = dataclasses.replace(PARAMS, max_category_share_pct=100)
    # Primeira rodada num savepoint, só para descobrir quem ficaria em primeiro.
    savepoint = db.begin_nested()
    decision_engine.analyze(db, params)
    first = _entering(db)
    savepoint.rollback()
    assert len(first) >= 2, "pré-condição: há vagas e candidatos"

    # Segunda rodada, do zero, barrando justamente o primeiro colocado.
    top = first[0]
    result = decision_engine.analyze(
        db, params, entry_guard=lambda product: _verdict(product.id == top)
    )

    entering = _entering(db)
    assert top not in entering
    assert result.held_brand_risk >= 1
    # A vaga que ele deixou foi preenchida por outro: o guarda não esvazia o portfólio.
    assert len(entering) == len(first)


def test_without_a_guard_nothing_changes(db: Session, candidates):
    result = decision_engine.analyze(db, PARAMS)
    assert result.held_brand_risk == 0


def test_the_verdict_uses_the_snapshot_price_title_and_category(db: Session, candidates):
    product = db.execute(select(Product).order_by(Product.id)).scalars().first()
    product.title = "Apple iPhone 15 128GB"
    db.flush()

    # Teto baixo: qualquer preço é "ticket alto", e a marca no título decide.
    low = risk_service.assess_product(db, product, price_ceiling=0.01)
    assert low.blocked and low.reason_code == "RISK_HIGH_TICKET_BRAND"

    # Teto altíssimo: a mesma marca num produto barato não é suspeita.
    high = risk_service.assess_product(db, product, price_ceiling=10_000_000)
    assert not high.blocked


def test_a_risky_category_blocks_even_an_unbranded_high_ticket_product(db: Session, candidates):
    product = db.execute(select(Product).order_by(Product.id)).scalars().first()
    product.title = "Monitor genérico 19 polegadas"
    db.flush()
    category = product.category_path[0]

    plain = risk_service.assess_product(db, product, price_ceiling=0.01)
    flagged = risk_service.assess_product(
        db, product, price_ceiling=0.01, brand_categories={category}
    )

    assert not plain.blocked
    assert flagged.blocked and flagged.reason_code == "RISK_HIGH_TICKET_CATEGORY"


# ---------- a rota realmente liga o guarda ----------


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_analyze_route_applies_the_configured_guard(client, db: Session, candidates):
    every_category = "Casa,Eletrônicos,Beleza,Esporte,Moda"
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, publish_price_ceiling="0.01", publish_brand_categories=every_category
    )

    response = client.post(
        "/api/v1/portfolio/analyze?dry_run=false", headers={"X-API-Key": "troque-esta-chave"}
    )

    summary = response.json()["summary"]
    assert summary["held_brand_risk"] > 0
    assert summary["recommendations_created"] == 0
    assert _entering(db) == []
