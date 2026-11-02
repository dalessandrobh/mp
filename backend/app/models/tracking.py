from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
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


class LinkClick(Base):
    """Um clique no nosso redirect `/go/{sub_id}`. Append-only.

    É a única medição de tráfego que temos no orgânico: a Shopee informa venda, nunca
    clique, e o Instagram não devolve clique de link na bio. Sem esta tabela não existe
    CVR e portanto não existe aprendizado (ver docs/plano-10k.md §3).

    Privacidade: o IP NUNCA é gravado. `visitor_hash` é sha256(ip + user-agent + sal +
    dia), truncado — serve para deduplicar o mesmo visitante no mesmo dia e não permite
    voltar ao IP.

    `is_bot` separa o pré-visualizador de link (WhatsApp, Facebook, Telegram buscam a
    URL para montar o card) do humano. Sem isso o CVR do orgânico vira ruído: o preview
    clica sempre e nunca compra.
    """

    __tablename__ = "link_clicks"
    __table_args__ = (
        Index("ix_link_clicks_product_id_click_date", "product_id", "click_date"),
        Index("ix_link_clicks_dedupe", "affiliate_link_id", "click_date", "visitor_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    affiliate_link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("affiliate_links.id"), nullable=False
    )
    # Desnormalizado de propósito: a agregação diária é por produto e não deve pagar join.
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Dia no fuso do Brasil, igual ao ledger e ao dashboard: a venda da Shopee vem nesse dia.
    click_date: Mapped[date] = mapped_column(Date, nullable=False)
    visitor_hash: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    referrer: Mapped[str | None] = mapped_column(Text)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Primeiro clique deste visitante neste link neste dia. O CVR usa só estes.
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
