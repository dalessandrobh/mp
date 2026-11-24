"""Pins do dia para o painel: o que o pacote gerou, pronto para abrir no Pinterest.

O painel mostra cada pin com um botão que abre o "Pin It" já preenchido (imagem, link
`pin` orgânico e descrição). A pessoa escolhe o quadro e salva: ela continua decidindo cada
pin. "Marcar como postado" grava em `social_posts` (canal `pin`, status PUBLISHED, sem
`external_post_id`) para o pin não sair de novo pela API e para o painel lembrar o que já
foi; como `social_posts` é append-only, a marca não se desfaz.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Marketplace, Product
from app.models.content import Creative
from app.models.social import SocialPost
from app.models.tracking import AffiliateLink
from app.services import content_service, pin_links
from app.services.publishing_constants import CHANNEL, STATUS_PUBLISHED, WINDOW_DAYS


class PinError(Exception):
    """Pedido que não pode ser atendido (criativo inexistente ou sem link)."""


@dataclass(frozen=True)
class PinCard:
    creative_id: int
    product_id: int
    title: str
    board: str | None
    description: str
    link: str
    image_url: str
    pin_it_url: str
    posted: bool
    created_at: datetime


def _marketplace_code(db: Session, product: Product) -> str:
    return db.execute(
        select(Marketplace.code).where(Marketplace.id == product.marketplace_id)
    ).scalar_one()


def _pin_link(db: Session, creative_id: int) -> AffiliateLink | None:
    return db.execute(
        select(AffiliateLink).where(
            AffiliateLink.creative_id == creative_id,
            AffiliateLink.channel == CHANNEL,
            AffiliateLink.revoked_at.is_(None),
        )
    ).scalar_one_or_none()


def _card(db: Session, creative: Creative, *, public_base: str, posted: bool) -> PinCard | None:
    product = db.get(Product, creative.product_id)
    link = _pin_link(db, creative.id)
    if product is None or link is None:
        return None
    category = content_service._category_name(db, product, _marketplace_code(db, product))
    description = creative.description or content_service._pin_description(
        creative.primary_text or "",
        " ".join(content_service._hashtags(product, [], category)),
    )
    tracked = f"{public_base}/go/{link.sub_id}"
    image = pin_links.image_url(public_base, creative.id)
    return PinCard(
        creative_id=creative.id,
        product_id=product.id,
        title=content_service._short_title(product.title, content_service.MAX_PIN_TITLE),
        board=content_service._board_name(category),
        description=description,
        link=tracked,
        image_url=image,
        pin_it_url=pin_links.pin_it_url(link=tracked, image=image, description=description),
        posted=posted,
        created_at=creative.created_at,
    )


def recent(db: Session, *, public_base: str, now: datetime | None = None) -> list[PinCard]:
    now = now or datetime.now(UTC)
    start = datetime.combine(now.astimezone(content_service.TZ).date(), datetime.min.time(),
                             content_service.TZ) - timedelta(days=WINDOW_DAYS - 1)
    creatives = db.execute(
        select(Creative)
        .where(Creative.format == content_service.FORMAT, Creative.created_at >= start)
        .order_by(Creative.id.desc())
    ).scalars().all()
    posted = set(
        db.execute(
            select(SocialPost.creative_id).where(
                SocialPost.channel == CHANNEL,
                SocialPost.status == STATUS_PUBLISHED,
                SocialPost.creative_id.in_([c.id for c in creatives]),
            )
        ).scalars()
    )
    cards = [
        card
        for c in creatives
        if (card := _card(db, c, public_base=public_base, posted=c.id in posted)) is not None
    ]
    # O que ainda falta postar vem primeiro; dentro de cada grupo, a ordem do pacote.
    return sorted(cards, key=lambda c: (c.posted, c.creative_id))


def mark_posted(db: Session, creative_id: int, *, now: datetime | None = None) -> bool:
    """Registra que a pessoa postou o pin. False se já estava marcado (idempotente)."""
    creative = db.get(Creative, creative_id)
    if creative is None or creative.format != content_service.FORMAT:
        raise PinError("pin não encontrado")
    link = _pin_link(db, creative_id)
    if link is None:
        raise PinError("o pin não tem link rastreado")
    existing = db.execute(
        select(SocialPost.status).where(
            SocialPost.creative_id == creative_id, SocialPost.channel == CHANNEL
        )
    ).scalar_one_or_none()
    if existing == STATUS_PUBLISHED:
        return False
    if existing is not None:
        # A linha é única por (criativo, canal) e imutável: não dá para trocar o status.
        raise PinError(f"o pin já tem um registro {existing} e não pode ser marcado")
    db.add(
        SocialPost(
            product_id=creative.product_id,
            creative_id=creative_id,
            affiliate_link_id=link.id,
            channel=CHANNEL,
            status=STATUS_PUBLISHED,
            published_at=now or datetime.now(UTC),
            payload={"manual": True, "source": "painel"},
        )
    )
    db.flush()
    return True
