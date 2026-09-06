from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AffiliateLink(Base):
    """O `sub_id` é a chave de atribuição: ele volta no ConversionReport da Shopee
    no campo `utmContent`, e é o que liga uma venda ao produto/campanha/criativo."""

    __tablename__ = "affiliate_links"
    __table_args__ = (
        Index(
            "ix_affiliate_links_product_id_active",
            "product_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    creative_id: Mapped[int | None] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    sub_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    utm_source: Mapped[str | None] = mapped_column(Text)
    utm_medium: Mapped[str | None] = mapped_column(Text)
    utm_campaign: Mapped[str | None] = mapped_column(Text)
    utm_content: Mapped[str | None] = mapped_column(Text)
    utm_term: Mapped[str | None] = mapped_column(Text)
    short_url: Mapped[str | None] = mapped_column(Text)
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
