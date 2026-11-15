"""Link rastreado para divulgação feita à mão (canal de WhatsApp, story, mensagem).

Por que existe: a Shopee só devolve a venda com `sub_id` se o link usado carregava um. Link
gerado direto no app da Shopee não carrega, e a venda chega sem origem (foi o que aconteceu
com os 7 pedidos de out-nov/2026). Aqui a pessoa informa o produto e o canal e recebe o link
do NOSSO redirect `/go/`, que conta o clique e leva o `sub_id` até a venda.

Só produtos que já estão no catálogo: o `sub_id` e o `/go/` dependem do id do produto. Produto
de fora precisa entrar pela descoberta antes.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter
from app.core.exceptions import DomainError
from app.domain.enums import ProductState
from app.models.catalog import Marketplace, Product
from app.models.tracking import AffiliateLink
from app.services import tracking_service

# `wa` = canal de WhatsApp; `ig` e `pin` já existem. Tudo aqui é orgânico.
MANUAL_CHANNELS = ("wa", "ig", "pin")

_URL_ITEM = (
    re.compile(r"/product/\d+/(\d+)"),  # shopee.com.br/product/{loja}/{item}
    re.compile(r"-i\.\d+\.(\d+)"),  # shopee.com.br/Nome-do-Produto-i.{loja}.{item}
)


class ManualLinkError(DomainError):
    status_code = 422
    code = "MANUAL_LINK_ERROR"


class ProductNotInCatalog(DomainError):
    status_code = 404
    code = "PRODUCT_NOT_IN_CATALOG"


@dataclass(frozen=True)
class ManualLink:
    product_id: int
    title: str | None
    channel: str
    sub_id: str
    tracked_url: str


def item_id_from(ref: str) -> str:
    """Aceita o id do item (só dígitos) ou a URL do produto da Shopee."""
    text = (ref or "").strip()
    if text.isdigit():
        return text
    for pattern in _URL_ITEM:
        found = pattern.search(text)
        if found:
            return found.group(1)
    raise ManualLinkError(
        "Não reconheci o produto. Cole a URL do produto na Shopee "
        "(…/product/<loja>/<item> ou …-i.<loja>.<item>) ou só o número do item."
    )


def create(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    ref: str,
    channel: str,
    public_base: str,
    max_sub_id_length: int,
) -> ManualLink:
    if channel not in MANUAL_CHANNELS:
        raise ManualLinkError(f"canal inválido; use um de {', '.join(MANUAL_CHANNELS)}")
    if not public_base:
        raise ManualLinkError("PUBLIC_BASE_URL vazia: sem ela o clique não seria medido")

    item_id = item_id_from(ref)
    product = db.execute(
        select(Product)
        .join(Marketplace, Marketplace.id == Product.marketplace_id)
        .where(Marketplace.code == adapter.code, Product.external_product_id == item_id)
    ).scalar_one_or_none()
    if product is None:
        raise ProductNotInCatalog(
            "Esse produto não está no catálogo do MP, então não dá para rastrear a venda "
            "dele. Ele precisa entrar pela descoberta primeiro.",
            details={"item_id": item_id},
        )

    result = tracking_service.generate_links(
        db, adapter, channel=channel, max_sub_id_length=max_sub_id_length,
        only_product_ids={product.id}, states=tuple(ProductState),
    )
    link = db.execute(
        select(AffiliateLink)
        .where(
            AffiliateLink.product_id == product.id,
            AffiliateLink.channel == channel,
            AffiliateLink.creative_id.is_(None),
            AffiliateLink.campaign_id.is_(None),
            AffiliateLink.revoked_at.is_(None),
        )
        .order_by(AffiliateLink.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if link is None or not link.short_url:
        raise ManualLinkError(
            "A Shopee recusou gerar o link deste produto: " + "; ".join(result.warnings)
        )
    return ManualLink(
        product_id=product.id, title=product.title, channel=channel, sub_id=link.sub_id,
        tracked_url=f"{public_base}/go/{link.sub_id}",
    )
