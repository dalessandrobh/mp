"""Dados da página pública de links ("link na bio").

Mostra só produto que já tem link emitido e não revogado: a página não chama o
marketplace para gerar link no meio da renderização — isso tornaria o tempo de resposta
dependente de uma API externa e, pior, criaria link a cada visita de robô.

Ordem: maior receita esperada por clique primeiro (`ev_v1`). É o que a vitrine deve
mostrar no topo, porque o primeiro item da página é o que recebe mais clique e o objetivo
é comissão, não popularidade. Sem EV calculado, cai no Opportunity Score.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.domain.enums import ProductState
from app.models.catalog import Product, ProductSnapshot
from app.models.funnel import ProductCurrentState
from app.models.scoring import OpportunityScore
from app.models.tracking import AffiliateLink
from app.services import ev_scoring

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
    ev_per_click: Decimal | None


def bio_items(
    db: Session, *, limit: int = 60, prefer_channel: str | None = None
) -> list[BioItem]:
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

    # Um link por produto: o mais recente que ainda vale. Com `prefer_channel`, o link desse
    # canal vem na frente (se existir): é o que faz o clique de uma página pensada para o
    # Pinterest entrar como `pin`, e não como o canal de um link antigo do mesmo produto.
    # Sem link do canal preferido, cai no mais recente: o produto não some da página.
    sub_by_product: dict[int, str] = {}
    for link in db.execute(
        select(AffiliateLink)
        .where(AffiliateLink.product_id.in_(ids), AffiliateLink.revoked_at.is_(None))
        .order_by(
            AffiliateLink.product_id,
            case((AffiliateLink.channel == prefer_channel, 0), else_=1),
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

    evs = ev_scoring.latest_evs(db)
    items = [
        BioItem(
            product_id=p.id,
            title=p.title,
            price=(snapshot_by_product.get(p.id).price if p.id in snapshot_by_product else None),
            image_url=p.image_url,
            sub_id=sub_by_product[p.id],
            score=score_by_product.get(p.id),
            ev_per_click=evs[p.id].ev_per_click if p.id in evs else None,
        )
        for p in products
        if p.id in sub_by_product  # sem link não há o que clicar
    ]
    # Quem tem EV vem antes de quem não tem; depois o Opportunity Score desempata.
    items.sort(
        key=lambda i: (
            i.ev_per_click is None,
            -(i.ev_per_click or Decimal(0)),
            -(i.score or Decimal(0)),
            i.product_id,
        )
    )
    return items[:limit]
