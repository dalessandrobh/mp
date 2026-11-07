"""Fila de aprovação de pins: o MP propõe, a pessoa decide, pin a pin.

Regra 4.3 das Diretrizes de Desenvolvedor do Pinterest: o app não pode "enable end users to
automatically initiate actions without specifically considering each action"; para um
agendador, "the end user must choose each Pin to be published". Até aqui o workflow 04
publicava sozinho até 10 pins por dia, escolhidos por algoritmo — exatamente o que a regra
descreve. Agora o algoritmo só **propõe**: um criativo só é publicado se existe uma decisão
APPROVED, gravada por um humano autenticado no painel.

Duas escolhas de desenho que importam:

* **A decisão é append-only e a mais recente vale.** Mudar de ideia é uma linha nova. O
  histórico de quem aprovou o quê não se perde, e não existe UPDATE a proteger.
* **Quem decide é sempre `human:<email>`.** Os endpoints de decisão exigem o JWT do painel;
  a chave do n8n é recusada. Se o n8n pudesse aprovar, o workflow aprovaria os próprios pins
  e a fila viraria decoração.

A aprovação NÃO contorna o guarda de réplica: um criativo aprovado de produto suspeito
continua barrado na publicação. A pessoa pode errar o clique; o guarda não pode.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, NotFound
from app.domain import brand_risk
from app.models.catalog import Product
from app.models.content import Creative
from app.models.social import PublishApproval, SocialPost
from app.services import risk_service
from app.services._funnel_queries import latest_snapshot
from app.services.content_service import FORMAT, TZ
from app.services.publishing_constants import (
    CHANNEL,
    DECISION_APPROVED,
    DECISIONS,
    WINDOW_DAYS,
)

# Estados mostrados na fila. PENDING = sem decisão; os demais vêm da decisão ou do post.
PENDING = "PENDING"


@dataclass(frozen=True)
class QueueItem:
    creative_id: int
    product_id: int
    title: str | None
    price: str | None
    commission_value: str | None
    image_url: str | None
    headline: str | None
    caption: str | None
    created_at: datetime
    status: str  # PENDING | APPROVED | REJECTED | PUBLISHED | BLOCKED | FAILED
    risk_blocked: bool
    risk_reason: str | None


def window_start(now: datetime, days: int = WINDOW_DAYS) -> datetime:
    today = now.astimezone(TZ).date()
    return datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), TZ)


def candidates(db: Session, *, now: datetime) -> list[Creative]:
    """Criativos da janela, do mais novo para o mais antigo."""
    return list(
        db.execute(
            select(Creative)
            .where(Creative.format == FORMAT, Creative.created_at >= window_start(now))
            .order_by(Creative.id.desc())
        ).scalars()
    )


def latest_decisions(db: Session, *, channel: str, creative_ids: list[int]) -> dict[int, str]:
    """Decisão vigente por criativo: a linha de maior id vence."""
    if not creative_ids:
        return {}
    decisions: dict[int, str] = {}
    rows = db.execute(
        select(PublishApproval.creative_id, PublishApproval.decision)
        .where(PublishApproval.channel == channel, PublishApproval.creative_id.in_(creative_ids))
        .order_by(PublishApproval.id)
    )
    for creative_id, decision in rows:
        decisions[creative_id] = decision
    return decisions


def approved_ids(db: Session, *, channel: str, creative_ids: list[int]) -> set[int]:
    decisions = latest_decisions(db, channel=channel, creative_ids=creative_ids)
    return {cid for cid, decision in decisions.items() if decision == DECISION_APPROVED}


def _posts_by_creative(db: Session, *, channel: str, creative_ids: list[int]) -> dict[int, str]:
    if not creative_ids:
        return {}
    return dict(
        db.execute(
            select(SocialPost.creative_id, SocialPost.status).where(
                SocialPost.channel == channel, SocialPost.creative_id.in_(creative_ids)
            )
        ).all()
    )


def awaiting_count(db: Session, *, channel: str = CHANNEL, now: datetime | None = None) -> int:
    """Criativos que ainda esperam uma decisão (sem decisão e sem post)."""
    now = now or datetime.now(UTC)
    ids = [c.id for c in candidates(db, now=now)]
    decided = latest_decisions(db, channel=channel, creative_ids=ids)
    posted = _posts_by_creative(db, channel=channel, creative_ids=ids)
    return sum(1 for i in ids if i not in decided and i not in posted)


def queue(
    db: Session,
    *,
    channel: str = CHANNEL,
    now: datetime | None = None,
    price_ceiling: float = brand_risk.DEFAULT_PRICE_CEILING,
    brand_categories: frozenset[str] = frozenset(),
) -> list[QueueItem]:
    now = now or datetime.now(UTC)
    creatives = candidates(db, now=now)
    ids = [c.id for c in creatives]
    decided = latest_decisions(db, channel=channel, creative_ids=ids)
    posted = _posts_by_creative(db, channel=channel, creative_ids=ids)

    items: list[QueueItem] = []
    for creative in creatives:
        product = db.get(Product, creative.product_id)
        snapshot = latest_snapshot(db, creative.product_id) if product else None

        verdict = (
            risk_service.assess_product(
                db, product, price_ceiling=price_ceiling, brand_categories=brand_categories
            )
            if product
            else brand_risk.assess(
                brand_risk.RiskInput(title=None, price=None, category_id=None),
                price_ceiling=price_ceiling,
                brand_categories=brand_categories,
            )
        )
        # O post, quando existe, é fato consumado e prevalece sobre a decisão.
        status = posted.get(creative.id) or decided.get(creative.id) or PENDING
        items.append(
            QueueItem(
                creative_id=creative.id,
                product_id=creative.product_id,
                title=product.title if product else None,
                price=str(snapshot.price) if snapshot and snapshot.price is not None else None,
                commission_value=(
                    str(snapshot.commission_value)
                    if snapshot and snapshot.commission_value is not None
                    else None
                ),
                image_url=product.image_url if product else None,
                headline=creative.headline,
                caption=creative.primary_text,
                created_at=creative.created_at,
                status=status,
                risk_blocked=verdict.blocked,
                risk_reason=verdict.reason_code if verdict.blocked else None,
            )
        )
    return items


@dataclass
class DecisionResult:
    recorded: int = 0
    unchanged: int = 0
    already_posted: int = 0


def decide(
    db: Session,
    *,
    creative_ids: list[int],
    decision: str,
    actor: str,
    channel: str = CHANNEL,
    now: datetime | None = None,
) -> DecisionResult:
    """Grava a decisão de uma pessoa. `actor` precisa ser `human:<email>`.

    A checagem do prefixo é a trava de última instância: mesmo que alguém ligue um endpoint
    errado a esta função, o n8n (ator "n8n") não consegue aprovar.
    """
    if not actor.startswith("human:"):
        raise DomainError("Só uma pessoa autenticada no painel pode aprovar a publicação")
    if decision not in DECISIONS:
        raise DomainError(f"decisão inválida: {decision!r}")
    ids = list(dict.fromkeys(creative_ids))
    if not ids:
        raise DomainError("nenhum criativo informado")

    now = now or datetime.now(UTC)
    creatives = {
        c.id: c
        for c in db.execute(
            select(Creative).where(Creative.id.in_(ids), Creative.format == FORMAT)
        ).scalars()
    }
    missing = [i for i in ids if i not in creatives]
    if missing:
        raise NotFound(f"criativo(s) inexistente(s): {missing}")

    current = latest_decisions(db, channel=channel, creative_ids=ids)
    posted = _posts_by_creative(db, channel=channel, creative_ids=ids)

    result = DecisionResult()
    for creative_id in ids:
        if creative_id in posted:
            result.already_posted += 1  # já saiu (ou foi barrado): decisão não muda mais nada
            continue
        if current.get(creative_id) == decision:
            result.unchanged += 1
            continue
        db.add(
            PublishApproval(
                creative_id=creative_id,
                product_id=creatives[creative_id].product_id,
                channel=channel,
                decision=decision,
                decided_by=actor,
            )
        )
        result.recorded += 1
    db.flush()
    return result
