"""Orquestra a criação de campanhas para os produtos elegíveis.

Escolhe quem recebe campanha e entrega ao AdsGateway; toda regra de segurança
mora no gateway, não aqui.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import PortfolioTier, ProductState
from app.models.ads import Ad
from app.models.tracking import AffiliateLink
from app.services._funnel_queries import products_in_state
from app.services.ads_gateway import AdsGateway, BundleRequest, BundleStatus
from app.services.portfolio_service import PortfolioParams
from app.services.tracking_service import LINKABLE_STATES


@dataclass
class AdsCreationResult:
    eligible: int = 0
    created: int = 0
    simulated: int = 0
    refused: int = 0
    aborted: bool = False
    stopped_by_limit: bool = False
    warnings: list[str] = field(default_factory=list)


def create_campaigns(
    db: Session, gateway: AdsGateway, params: PortfolioParams
) -> AdsCreationResult:
    result = AdsCreationResult()

    for state in LINKABLE_STATES:
        is_test = state is ProductState.TEST
        tier = PortfolioTier.EXPLORATION if is_test else PortfolioTier.EXPLOITATION
        for product in products_in_state(db, state):
            link = db.execute(
                select(AffiliateLink)
                .where(AffiliateLink.product_id == product.id, AffiliateLink.revoked_at.is_(None))
                .order_by(AffiliateLink.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            already_advertised = db.execute(
                select(Ad.id).where(Ad.product_id == product.id).limit(1)
            ).first()
            if link is None or already_advertised:
                continue

            result.eligible += 1
            outcome = gateway.create_campaign_bundle(
                BundleRequest(
                    product_id=product.id,
                    affiliate_link_id=link.id,
                    name=f"mp-{link.sub_id}",
                    daily_budget=params.min_daily_test_budget,
                    tier=tier,
                )
            )

            if outcome.status is BundleStatus.CREATED:
                result.created += 1
            elif outcome.status is BundleStatus.SIMULATED:
                result.simulated += 1
            elif outcome.status is BundleStatus.ABORTED:
                result.aborted = True
                result.warnings.append(f"ABORT: {outcome.detail}")
                return result
            elif outcome.status is BundleStatus.STOPPED_LIMIT:
                result.stopped_by_limit = True
                result.warnings.append(outcome.detail or "limite por execução")
                return result
            elif outcome.status is BundleStatus.REFUSED_AUTONOMY:
                result.refused += 1
                result.warnings.append(outcome.detail or "autonomia insuficiente")
                return result  # vale para todos os produtos; não adianta repetir
            else:
                result.refused += 1
                result.warnings.append(f"produto {product.id}: {outcome.detail}")

    return result
