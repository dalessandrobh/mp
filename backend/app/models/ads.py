from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import CampaignReviewStatus
from app.models._types import campaign_review_status_enum


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        # Invariante de segurança gravada no schema, não só no código.
        CheckConstraint("created_paused = TRUE", name="campaigns_must_be_created_paused"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default="meta")
    ad_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    review_status: Mapped[CampaignReviewStatus] = mapped_column(
        campaign_review_status_enum, nullable=False, server_default="UNREVIEWED"
    )
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_by_run_id: Mapped[int | None] = mapped_column(BigInteger)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdSet(Base):
    __tablename__ = "ad_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    targeting: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Ad(Base):
    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ad_set_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ad_sets.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    creative_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("creatives.id"))
    affiliate_link_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("affiliate_links.id")
    )
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
