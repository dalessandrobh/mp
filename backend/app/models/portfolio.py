from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import PortfolioTier
from app.models._types import portfolio_tier_enum


class PortfolioProduct(Base):
    __tablename__ = "portfolio_products"
    __table_args__ = (
        # Um produto só pode estar ativo uma vez no portfólio.
        Index(
            "uq_portfolio_products_active_product",
            "product_id",
            unique=True,
            postgresql_where=text("exited_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    tier: Mapped[PortfolioTier] = mapped_column(portfolio_tier_enum, nullable=False)
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason_code: Mapped[str | None] = mapped_column(Text)
    allocated_daily_budget: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    priority_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, server_default="1.0"
    )
    entry_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    exit_decision_id: Mapped[int | None] = mapped_column(BigInteger)


class PortfolioSnapshot(Base):
    """Fotografia diária do portfólio para gráficos históricos."""

    __tablename__ = "portfolio_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    active_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exploration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exploitation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_daily_budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    recommended_size: Mapped[int | None] = mapped_column(Integer)
    sizing_rationale: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
