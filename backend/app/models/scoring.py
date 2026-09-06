from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import SettlementStatus
from app.models._types import settlement_status_enum


class OpportunityScore(Base):
    """Append-only e versionado: o score de ontem não é reescrito pelo de hoje."""

    __tablename__ = "opportunity_scores"
    __table_args__ = (
        Index("ix_opportunity_scores_product_id_computed_at", "product_id", "computed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # false => score é indicativo, não decisório.
    data_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    llm_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PerformanceScore(Base):
    __tablename__ = "performance_scores"
    __table_args__ = (UniqueConstraint("product_id", "window_days", "computed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    data_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Passou MIN_CLICKS_FOR_DECISION / MIN_IMPRESSIONS_FOR_DECISION?
    sample_sufficient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    settlement: Mapped[SettlementStatus] = mapped_column(settlement_status_enum, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
