"""Publicação em rede social: o que foi postado, e o segredo que rotaciona.

`social_posts` é append-only como o resto do histórico do MP: um post publicado é fato
consumado, e editar a linha depois apagaria a única prova de que o pin saiu — que é
justamente o que liga o clique medido ao produto.

`oauth_tokens` é a **exceção deliberada** à regra append-only, e vale dizer por quê: o
refresh token do Pinterest rotaciona a cada renovação (ver `pinterest/auth.py`). Guardar
cada versão num histórico append-only acumularia segredo válido em linha antiga sem
nenhum ganho — o token velho não serve para auditar nada e serve para vazar. Então aqui
a linha é mutável e única por provedor, e o histórico que importa (quando renovou, quanto
falta) vai para o log e para o alerta.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SocialPost(Base):
    __tablename__ = "social_posts"
    __table_args__ = (
        # Um criativo não vai duas vezes para a mesma rede: é a trava de idempotência que
        # protege contra workflow re-executado.
        UniqueConstraint("creative_id", "channel", name="uq_social_posts_creative_channel"),
        Index("ix_social_posts_product_id_created_at", "product_id", "created_at"),
        Index("ix_social_posts_channel_status", "channel", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    creative_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("creatives.id"), nullable=False
    )
    affiliate_link_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("affiliate_links.id")
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    # PUBLISHED | DRY_RUN | BLOCKED | FAILED
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    external_post_id: Mapped[str | None] = mapped_column(Text)
    post_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishApproval(Base):
    """Decisão HUMANA de publicar (ou não) um criativo num canal. Append-only.

    Existe por causa da regra 4.3 das Diretrizes de Desenvolvedor do Pinterest: o app não
    pode "enable end users to automatically initiate actions without specifically
    considering each action" — num agendador, "the end user must choose each Pin to be
    published". O MP escolhe candidatos; quem decide o que sai é a pessoa, pin a pin.

    A decisão que vale é a MAIS RECENTE do par (criativo, canal). Mudar de ideia é uma
    linha nova, não um UPDATE: assim o histórico mostra quem aprovou, quando, e que
    houve arrependimento antes de o pin sair.

    `decided_by` é sempre `human:<email>`. Nenhum caminho do n8n grava aqui: um workflow que
    aprovasse os próprios pins reintroduziria exatamente a automação que a regra proíbe.
    """

    __tablename__ = "publish_approvals"
    __table_args__ = (
        Index("ix_publish_approvals_creative_channel_id", "creative_id", "channel", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creative_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("creatives.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    # 'APPROVED' | 'REJECTED'
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OauthToken(Base):
    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    access_token: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
