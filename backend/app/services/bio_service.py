"""Dados da página pública de links ("link na bio").

Mostra só produto que já tem link emitido e não revogado: a página não chama o
marketplace para gerar link no meio da renderização — isso tornaria o tempo de resposta
dependente de uma API externa e, pior, criaria link a cada visita de robô.

Ordem: maior Opportunity Score primeiro, porque é o que o motor hoje considera melhor
oferta. Quando o ranking por EV entrar (docs/plano-10k.md §3), troca-se a ordem aqui.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ProductState
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState
from app.models.scoring import OpportunityScore
from app.models.tracking import AffiliateLink

# Mesmos estados do pacote de conteúdo: o que está em teste ou provado é o que se divulga.
VISIBLE_STATES = (ProductState.WINNER, ProductState.ACTIVE, ProductState.TEST)


@dataclass(frozen=True)
class BioItem:
    product_id: int
    title: str
    price: Decimal | None
    image_url: str | None
    sub_id: str
    score: Decimal | None


def bio_items(db: Session, *, limit: int = 60) -> list[BioItem]:
    products = list(
        db.execute(
            select(Product)
            .join(ProductCurrentState, ProductCurrentState.product_id == Product.id)
            .where(ProductCurrentState.state.in_(VISIBLE_STATES))
        ).scalars()
    )
    if not products:
        return []

    ids = [p.id for p in products]

    # Um link por produto: o mais recente que ainda vale.
    sub_by_product: dict[int, str] = {}
    for link in db.execute(
        select(AffiliateLink)
        .where(AffiliateLink.product_id.in_(ids), AffiliateLink.revoked_at.is_(None))
        .order_by(
            AffiliateLink.product_id,
            AffiliateLink.generated_at.desc(),
            AffiliateLink.id.desc(),
        )
    ).scalars():
        sub_by_product.setdefault(link.product_id, link.sub_id)

    snapshot_by_product: dict[int, ProductSnapshot] = {}
    for snapshot in db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id.in_(ids))
        .order_by(
            ProductSnapshot.product_id,
            ProductSnapshot.captured_at.desc(),
            ProductSnapshot.id.desc(),
        )
    ).scalars():
        snapshot_by_product.setdefault(snapshot.product_id, snapshot)

    score_by_product: dict[int, Decimal] = {}
    for score in db.execute(
        select(OpportunityScore)
        .where(OpportunityScore.product_id.in_(ids))
        .order_by(
            OpportunityScore.product_id,
            OpportunityScore.computed_at.desc(),
            OpportunityScore.id.desc(),
        )
    ).scalars():
        score_by_product.setdefault(score.product_id, score.score)

    items = [
        BioItem(
            product_id=p.id,
            title=p.title,
            price=(snapshot_by_product.get(p.id).price if p.id in snapshot_by_product else None),
            image_url=p.image_url,
            sub_id=sub_by_product[p.id],
            score=score_by_product.get(p.id),
        )
        for p in products
        if p.id in sub_by_product  # sem link não há o que clicar
    ]
    items.sort(key=lambda i: (-(i.score or Decimal(0)), i.product_id))
    return items[:limit]
