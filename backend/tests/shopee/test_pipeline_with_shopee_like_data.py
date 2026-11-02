"""O funil inteiro com um marketplace que nunca informa estoque nem nº de avaliações."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import ProductOffer
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.domain.enums import ProductState
from app.models.catalog import Marketplace
from app.models.funnel import ProductCurrentState
from app.models.scoring import OpportunityScore
from app.services import discovery_service, opportunity_scoring, qualification_service


class ShopeeLikeAdapter(MockAdapter):
    """Mesmo catálogo do mock, mas sem os campos que a Shopee nunca entrega."""

    code = "shopee_like"
    unsupported_fields = frozenset({"stock", "rating_count", "original_price"})

    def search_products(self, *, keyword=None, limit=50):
        return [
            ProductOffer(
                external_product_id=o.external_product_id, title=o.title,
                product_url=o.product_url, price=Decimal("120.00"),
                commission_rate=Decimal("0.08"), rating=Decimal("4.7"), sales_volume=800,
            )
            for o in super().search_products(keyword=keyword, limit=limit)[:6]
        ]


def _count(db, state):
    return db.execute(
        select(func.count()).select_from(ProductCurrentState)
        .where(ProductCurrentState.state == state)
    ).scalar_one()


def test_discovery_records_what_the_marketplace_never_reports(db: Session):
    discovery_service.run_discovery(db, ShopeeLikeAdapter(), limit=10)

    config = db.execute(
        select(Marketplace.config).where(Marketplace.code == "shopee_like")
    ).scalar_one()
    assert config["unsupported_fields"] == ["original_price", "rating_count", "stock"]


def test_products_get_decisive_scores_and_are_promoted_despite_the_missing_fields(db: Session):
    discovery_service.run_discovery(db, ShopeeLikeAdapter(), limit=10)
    qualification_service.run_qualification(db)

    scored = opportunity_scoring.run_opportunity_scoring(db)
    promoted = opportunity_scoring.run_promotion(db)

    assert scored.scored == 6
    scores = db.execute(select(OpportunityScore)).scalars().all()
    assert all(s.data_available for s in scores)
    assert all(s.algorithm_version == "opp_v2" for s in scores)
    assert promoted.promoted == 6 and promoted.held_indicative == 0
    assert _count(db, ProductState.CANDIDATE) == 6


def test_the_same_products_under_the_mock_remain_indicative_without_declaration(db: Session):
    """Sem declarar a ausência estrutural, o mesmo dado travaria o funil: o motivo do opp_v2."""

    class Undeclared(ShopeeLikeAdapter):
        code = "undeclared"
        unsupported_fields = frozenset()

    discovery_service.run_discovery(db, Undeclared(), limit=10)
    qualification_service.run_qualification(db)
    opportunity_scoring.run_opportunity_scoring(db)

    promoted = opportunity_scoring.run_promotion(db)

    assert promoted.promoted == 0 and promoted.held_indicative == 6
