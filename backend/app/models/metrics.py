from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import SettlementStatus
from app.models._types import settlement_status_enum


class AdMetricsRaw(Base):
    """Ingestão bruta append-only. Nunca agregamos por cima do bruto sem guardá-lo."""

    __tablename__ = "ad_metrics_raw"
    __table_args__ = (
        UniqueConstraint("source", "metric_date", "external_ad_id", "ingested_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    external_ad_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversionRaw(Base):
    """Conversões brutas do marketplace.

    `source` separa as duas leituras do mesmo pedido: 'conversion_report' traz a
    comissão estimada em horas, 'validated_report' traz a comissão liquidada em
    dias. O mesmo pedido aparece nos dois — por isso `source` entra na chave.
    """

    __tablename__ = "conversions_raw"
    __table_args__ = (
        UniqueConstraint("marketplace_id", "source", "external_order_id", "sub_id"),
        Index("ix_conversions_raw_sub_id_conversion_date", "sub_id", "conversion_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("marketplaces.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(Text)
    # Pode vir NULL: conversão não atribuível. Nunca inventamos atribuição.
    sub_id: Mapped[str | None] = mapped_column(Text)
    conversion_date: Mapped[date | None] = mapped_column(Date)
    commission_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    order_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str | None] = mapped_column(Text)
    fraud_status: Mapped[str | None] = mapped_column(Text)
    settlement: Mapped[SettlementStatus] = mapped_column(
        settlement_status_enum, nullable=False, server_default="PROVISIONAL"
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PerformanceDaily(Base):
    """Fato consolidado. Upsert por chave natural; toda revisão é registrada."""

    __tablename__ = "performance_daily"
    __table_args__ = (
        UniqueConstraint("metric_date", "product_id", "campaign_id", "channel"),
        Index("ix_performance_daily_product_id_metric_date", "product_id", "metric_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("campaigns.id"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    conversions: Mapped[int | None] = mapped_column(Integer)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cvr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    roi: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    roas: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    epc: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cost_data_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    revenue_data_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    settlement: Mapped[SettlementStatus] = mapped_column(
        settlement_status_enum, nullable=False, server_default="PROVISIONAL"
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PerformanceDailyRevision(Base):
    """O ROI de ontem mudou? Aqui está o antes."""

    __tablename__ = "performance_daily_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    performance_daily_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("performance_daily.id"), nullable=False
    )
    previous_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    revised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
