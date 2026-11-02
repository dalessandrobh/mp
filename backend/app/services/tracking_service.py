"""Tracking: gera o sub_id e o link de afiliado dos produtos em teste.

Gerar link é idempotente por construção: o mesmo produto/campanha/criativo/canal
no mesmo dia produz o mesmo sub_id, e um sub_id já registrado devolve o link
existente em vez de criar outro (a coluna é UNIQUE).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter
from app.core.exceptions import DomainError
from app.domain import sub_id as sub_id_format
from app.domain.enums import ProductState
from app.models.catalog import Marketplace, Product
from app.models.tracking import AffiliateLink
from app.services._funnel_queries import products_in_state

# Produtos nestes estados já recebem tráfego pago (ou estão prestes a).
LINKABLE_STATES = (ProductState.TEST, ProductState.ACTIVE, ProductState.WINNER)

MARKETPLACE_PREFIX = {"shopee": "shp", "mock": "mck"}


@dataclass
class LinkGenerationResult:
    created: int = 0
    already_existing: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)


def _prefix_for(adapter: MarketplaceAdapter) -> str:
    try:
        return MARKETPLACE_PREFIX[adapter.code]
    except KeyError as exc:
        raise DomainError(f"marketplace '{adapter.code}' sem prefixo de sub_id") from exc


def generate_links(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    channel: str,
    max_sub_id_length: int,
    campaign_id: int | None = None,
    creative_id: int | None = None,
) -> LinkGenerationResult:
    prefix = _prefix_for(adapter)
    today = datetime.now(UTC).date()
    result = LinkGenerationResult()

    # Só os produtos DESTE marketplace: link e prefixo de sub_id são do adapter ativo. Produto
    # de outro marketplace (ex.: sobra do mock depois de ligar a Shopee) receberia um
    # sub_id com o prefixo errado e um link que o marketplace real não reconhece.
    own_marketplace = db.execute(
        select(Marketplace.id).where(Marketplace.code == adapter.code)
    ).scalar_one_or_none()
    products: list[Product] = []
    for state in LINKABLE_STATES:
        products.extend(
            p for p in products_in_state(db, state) if p.marketplace_id == own_marketplace
        )

    for product in products:
        try:
            sub_id = sub_id_format.build(
                marketplace_prefix=prefix,
                product_id=product.id,
                channel=channel,
                day=today,
                campaign_id=campaign_id,
                creative_id=creative_id,
                max_length=max_sub_id_length,
            )
        except DomainError as exc:
            # Falha alto e segue: um produto problemático não trava os outros.
            result.failed += 1
            result.warnings.append(f"produto {product.id}: {exc.message}")
            continue

        exists = db.execute(
            select(AffiliateLink.id).where(AffiliateLink.sub_id == sub_id)
        ).first()
        if exists:
            result.already_existing += 1
            continue

        link = adapter.generate_affiliate_link(
            origin_url=product.product_url, sub_ids=(sub_id,)
        )
        db.add(
            AffiliateLink(
                product_id=product.id,
                campaign_id=campaign_id,
                creative_id=creative_id,
                channel=channel,
                sub_id=sub_id,
                utm_source=channel,
                utm_medium="cpc",
                utm_campaign=sub_id.split("-")[1],
                utm_content=sub_id.split("-")[3],
                utm_term=sub_id.split("-")[2],
                short_url=link.short_url,
                raw_url=product.product_url,
            )
        )
        result.created += 1

    db.flush()
    return result


def resolve_product_id(db: Session, sub_id: str) -> int | None:
    """Venda -> produto. Confirma no banco: só vale sub_id que nós emitimos."""
    return db.execute(
        select(AffiliateLink.product_id).where(AffiliateLink.sub_id == sub_id)
    ).scalar_one_or_none()
