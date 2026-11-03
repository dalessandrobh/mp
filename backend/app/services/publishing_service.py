"""Publica os criativos do dia na rede social. Fecha o laço do tráfego orgânico.

Antes disto o pacote de conteúdo chegava no WhatsApp e alguém postava à mão — o que
limitava o alcance ao tempo livre do operador. O laço agora é: descobre -> qualifica ->
pontua (EV) -> gera link -> gera legenda -> **publica** -> conta clique em /go/ -> o EV
deixa de ser prior e passa a ser medição.

Três decisões que não são óbvias:

1. **Canal próprio.** O link do `content_service` tem canal `ig`. Se o pin usasse esse
   link, o clique do Pinterest entraria como Instagram e a CVR por canal viraria ficção.
   Então aqui se gera link com canal `pin`. O canal é parâmetro explícito e NÃO vem de
   `adapter.code`: `mock_social` tem underline, que o sub_id recusa — e, mais importante,
   um ensaio com o mock deve produzir o mesmo canal que a produção.

2. **A divulgação de afiliado é cortada por último.** A descrição do pin tem orçamento de
   800 caracteres; se o texto estourar, quem se perde é o fim — que é exatamente onde a
   divulgação fica. Então o orçamento é reservado para ela ANTES de truncar a legenda.
   Post sem divulgação é problema de lei e de termos da Shopee, não de estética.

3. **Sem `public_base` não publica.** O pin tem de apontar para o nosso /go/, não para o
   link curto da Shopee: é o /go/ que conta o clique e é ele que mantém a URL com o id de
   afiliado fora de página indexável (Termos 4.3k). Sem base pública configurada, publicar
   seria queimar alcance sem medir nada.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter
from app.adapters.social.base import PostDraft, SocialAdapter, SocialError, fit
from app.domain import brand_risk
from app.models.catalog import Product, ProductSnapshot
from app.models.content import Creative
from app.models.social import SocialPost
from app.models.tracking import AffiliateLink
from app.services import tracking_service
from app.services._funnel_queries import latest_snapshot
from app.services.content_service import DISCLOSURE, FORMAT, TZ

logger = logging.getLogger(__name__)

CHANNEL = "pin"
STATUS_PUBLISHED = "PUBLISHED"
STATUS_DRY_RUN = "DRY_RUN"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"


@dataclass
class PublishResult:
    considered: int = 0
    published: int = 0
    dry_run: int = 0
    blocked: int = 0
    failed: int = 0
    already_published: int = 0
    warnings: list[str] = field(default_factory=list)
    posts: list[dict] = field(default_factory=list)


def _today_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(TZ).date(), datetime.min.time(), TZ)


def _pending_creatives(db: Session, *, channel: str, now: datetime) -> list[Creative]:
    """Criativos de hoje que ainda não foram para este canal.

    A trava real é a UNIQUE (creative_id, channel) no banco; esta consulta só evita a
    tentativa. Workflow re-executado no mesmo dia não republica.
    """
    done = set(
        db.execute(select(SocialPost.creative_id).where(SocialPost.channel == channel)).scalars()
    )
    creatives = db.execute(
        select(Creative)
        .where(Creative.format == FORMAT, Creative.created_at >= _today_start(now))
        .order_by(Creative.id)
    ).scalars()
    return [c for c in creatives if c.id not in done]


def _link_for(
    db: Session,
    marketplace: MarketplaceAdapter,
    *,
    product_id: int,
    creative_id: int,
    channel: str,
    max_sub_id_length: int,
) -> AffiliateLink | None:
    existing = db.execute(
        select(AffiliateLink).where(
            AffiliateLink.product_id == product_id,
            AffiliateLink.creative_id == creative_id,
            AffiliateLink.channel == channel,
            AffiliateLink.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    tracking_service.generate_links(
        db,
        marketplace,
        channel=channel,
        max_sub_id_length=max_sub_id_length,
        creative_id=creative_id,
        only_product_ids={product_id},
    )
    return db.execute(
        select(AffiliateLink).where(
            AffiliateLink.product_id == product_id,
            AffiliateLink.creative_id == creative_id,
            AffiliateLink.channel == channel,
            AffiliateLink.revoked_at.is_(None),
        )
    ).scalar_one_or_none()


def _description(caption: str, limit: int) -> str:
    """Legenda + divulgação, com a divulgação protegida do truncamento."""
    reserved = len(DISCLOSURE) + 2  # '\n\n'
    body = fit(caption, max(limit - reserved, 1))
    return f"{body}\n\n{DISCLOSURE}"


def _record(
    db: Session,
    *,
    product_id: int,
    creative_id: int,
    channel: str,
    status: str,
    link_id: int | None = None,
    reason_code: str | None = None,
    external_post_id: str | None = None,
    post_url: str | None = None,
    published_at: datetime | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        SocialPost(
            product_id=product_id,
            creative_id=creative_id,
            affiliate_link_id=link_id,
            channel=channel,
            status=status,
            reason_code=reason_code,
            external_post_id=external_post_id,
            post_url=post_url,
            published_at=published_at,
            payload=payload,
        )
    )
    db.flush()


def publish_pending(
    db: Session,
    social: SocialAdapter,
    marketplace: MarketplaceAdapter,
    *,
    public_base: str,
    max_sub_id_length: int,
    max_per_run: int,
    dry_run: bool,
    channel: str = CHANNEL,
    price_ceiling: float = brand_risk.DEFAULT_PRICE_CEILING,
    brand_categories: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> PublishResult:
    now = now or datetime.now(UTC)
    result = PublishResult()

    if not public_base:
        result.warnings.append(
            "PUBLIC_BASE_URL vazia: não publiquei nada. O pin tem de apontar para /go/ "
            "para o clique ser medido e a URL de afiliado ficar fora de página indexável."
        )
        return result

    limits = social.limits
    for creative in _pending_creatives(db, channel=channel, now=now):
        if result.published + result.dry_run >= max_per_run:
            break
        result.considered += 1
        product = db.get(Product, creative.product_id)
        if product is None:
            result.failed += 1
            result.warnings.append(f"criativo {creative.id}: produto não existe")
            continue

        snapshot: ProductSnapshot | None = latest_snapshot(db, product.id)
        verdict = brand_risk.assess(
            brand_risk.RiskInput(
                title=product.title,
                price=float(snapshot.price) if snapshot and snapshot.price is not None else None,
                category_id=(product.category_path or [None])[0],
            ),
            price_ceiling=price_ceiling,
            brand_categories=brand_categories,
        )
        if verdict.blocked:
            result.blocked += 1
            _record(
                db,
                product_id=product.id,
                creative_id=creative.id,
                channel=channel,
                status=STATUS_BLOCKED,
                reason_code=verdict.reason_code,
                payload={"why": verdict.why, "guard": "brand_risk"},
            )
            continue

        link = _link_for(
            db,
            marketplace,
            product_id=product.id,
            creative_id=creative.id,
            channel=channel,
            max_sub_id_length=max_sub_id_length,
        )
        if link is None:
            result.failed += 1
            result.warnings.append(f"produto {product.id}: sem link rastreado no canal {channel}")
            continue

        draft = PostDraft(
            title=fit(product.title or creative.headline or "Achado", limits.title),
            description=_description(
                creative.primary_text or creative.headline or "", limits.description
            ),
            link=f"{public_base}/go/{link.sub_id}",
            image_url=product.image_url or "",
            alt_text=product.title,
        )
        problems = draft.problems(limits)
        if problems:
            result.failed += 1
            result.warnings.append(f"produto {product.id}: {'; '.join(problems)}")
            _record(
                db,
                product_id=product.id,
                creative_id=creative.id,
                channel=channel,
                status=STATUS_FAILED,
                link_id=link.id,
                reason_code="DRAFT_INVALID",
                payload={"problems": list(problems)},
            )
            continue

        if dry_run:
            result.dry_run += 1
            _record(
                db,
                product_id=product.id,
                creative_id=creative.id,
                channel=channel,
                status=STATUS_DRY_RUN,
                link_id=link.id,
                payload={"title": draft.title, "link": draft.link},
            )
            result.posts.append(
                {"product_id": product.id, "title": draft.title, "link": draft.link,
                 "status": STATUS_DRY_RUN}
            )
            continue

        try:
            published = social.publish(draft)
        except SocialError as exc:
            # Falha de uma rede não derruba o lote: registra e segue.
            result.failed += 1
            result.warnings.append(f"produto {product.id}: {exc}")
            _record(
                db,
                product_id=product.id,
                creative_id=creative.id,
                channel=channel,
                status=STATUS_FAILED,
                link_id=link.id,
                reason_code=type(exc).__name__,
                payload={"error": str(exc)[:500]},
            )
            continue

        result.published += 1
        _record(
            db,
            product_id=product.id,
            creative_id=creative.id,
            channel=channel,
            status=STATUS_PUBLISHED,
            link_id=link.id,
            external_post_id=published.external_post_id,
            post_url=published.url,
            published_at=now,
            payload=published.raw,
        )
        result.posts.append(
            {
                "product_id": product.id,
                "title": draft.title,
                "link": draft.link,
                "post_url": published.url,
                "status": STATUS_PUBLISHED,
            }
        )

    return result


def published_today(db: Session, *, channel: str = CHANNEL, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = db.execute(
        select(SocialPost.id).where(
            SocialPost.channel == channel,
            SocialPost.status == STATUS_PUBLISHED,
            SocialPost.created_at >= _today_start(now),
        )
    ).scalars()
    return len(list(rows))
