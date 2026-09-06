from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import ProductState
from app.models._types import product_state_enum


class ProductStateTransition(Base):
    """Append-only. A verdade sobre por que este produto está neste estado."""

    __tablename__ = "product_state_transitions"
    __table_args__ = (
        Index("ix_product_state_transitions_product_id_created_at", "product_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    from_state: Mapped[ProductState | None] = mapped_column(product_state_enum)
    to_state: Mapped[ProductState] = mapped_column(product_state_enum, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[int | None] = mapped_column(BigInteger)
    # 'ai_engine' | 'human:<email>' | 'system'
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_used: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductCurrentState(Base):
    """Estado corrente desnormalizado. Mantido exclusivamente pela state machine."""

    __tablename__ = "product_current_state"

    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id"), primary_key=True
    )
    state: Mapped[ProductState] = mapped_column(product_state_enum, nullable=False)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_transition: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product_state_transitions.id")
    )
