"""Decide O QUE cada anúncio promove e QUANTO se aceita pagar por clique.

O anúncio do Pinterest não cria conteúdo: promove um pin que já existe. Por isso a campanha
só nasce para produto com pin PUBLICADO (`social_posts`), e o pin é o ponto de partida —
anúncio e orgânico mostram a mesma coisa, o que também mantém o anúncio coerente com a
página de destino (Diretrizes de Publicidade do Pinterest).

Duas decisões que não estão óbvias no código:

**Canal `pinads`, não `pin`.** O pin orgânico aponta para um link com canal `pin`. Se o
anúncio herdasse esse destino, o clique pago entraria como orgânico e a CVR por canal — a
razão de existir do sub_id — viraria uma média sem significado. O anúncio leva
`destination_url` próprio, com link de canal `pinads`.

**O lance nunca passa do piso de receita por clique.** O piso é `comissão × CVR do quantil
10%` (o mesmo corte que o EV usa para decidir manter ou cortar). Pagar mais que isso por
clique é, por construção, apostar que o produto converte melhor do que o pior cenário
plausível. O teto de configuração (`PINTEREST_ADS_MAX_CPC`) limita o lance mesmo quando o
piso é alto.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter
from app.models.catalog import Product
from app.models.social import SocialPost
from app.services import ev_scoring, publishing_service
from app.services.publishing_constants import ADS_CHANNEL

CHANNEL = ADS_CHANNEL
ORGANIC_CHANNEL = publishing_service.CHANNEL
CENT = Decimal("0.01")


@dataclass(frozen=True)
class AdTarget:
    affiliate_link_id: int
    pin_id: str
    destination_url: str
    creative_id: int
    bid: Decimal


@dataclass(frozen=True)
class Skip:
    reason: str


class PinterestAdTargets:
    def __init__(
        self,
        db: Session,
        marketplace: MarketplaceAdapter,
        *,
        public_base: str,
        max_sub_id_length: int,
        max_cpc: Decimal,
    ) -> None:
        self._db = db
        self._marketplace = marketplace
        self._public_base = public_base
        self._max_sub_id_length = max_sub_id_length
        self._max_cpc = max_cpc

    def resolve(self, product: Product) -> AdTarget | Skip:
        if not self._public_base:
            return Skip("sem PUBLIC_BASE_URL")

        post = self._db.execute(
            select(SocialPost)
            .where(
                SocialPost.product_id == product.id,
                SocialPost.channel == ORGANIC_CHANNEL,
                SocialPost.status == publishing_service.STATUS_PUBLISHED,
                SocialPost.external_post_id.is_not(None),
            )
            .order_by(SocialPost.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if post is None:
            return Skip("sem pin publicado")

        bid = self._bid(product)
        if isinstance(bid, Skip):
            return bid

        link = publishing_service.link_for(
            self._db,
            self._marketplace,
            product_id=product.id,
            creative_id=post.creative_id,
            channel=CHANNEL,
            max_sub_id_length=self._max_sub_id_length,
        )
        if link is None:
            return Skip("sem link rastreado no canal pinads")

        return AdTarget(
            affiliate_link_id=link.id,
            pin_id=post.external_post_id,
            destination_url=f"{self._public_base}/go/{link.sub_id}",
            creative_id=post.creative_id,
            bid=bid,
        )

    def _bid(self, product: Product) -> Decimal | Skip:
        ev = ev_scoring.latest_ev(self._db, product.id)
        if ev is None:
            return Skip("sem EV calculado")
        floor = (ev.commission_value * ev.cvr_lower).quantize(CENT, rounding=ROUND_DOWN)
        bid = min(floor, self._max_cpc)
        if bid <= 0:
            return Skip(f"piso de receita por clique R$ {floor} não sustenta nenhum lance")
        return bid
