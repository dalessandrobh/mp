from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import DecisionMode, DecisionType
from app.models._types import decision_mode_enum, decision_type_enum


class AiRecommendation(Base):
    """Modo RECOMMEND: a IA propõe, um humano decide."""

    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    decision_type: Mapped[DecisionType] = mapped_column(decision_type_enum, nullable=False)
    # 'product' | 'portfolio' | 'parameter' | 'campaign'
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(Text)
    # O QUE / POR QUE / DADOS USADOS
    rationale: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    expected_impact: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiDecision(Base):
    """Append-only. Nunca UPDATE, nunca DELETE. É o rastro de tudo que a IA fez."""

    __tablename__ = "ai_decisions"
    __table_args__ = (Index("ix_ai_decisions_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    recommendation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_recommendations.id")
    )
    mode: Mapped[DecisionMode] = mapped_column(decision_mode_enum, nullable=False)
    decision_type: Mapped[DecisionType] = mapped_column(decision_type_enum, nullable=False)
    autonomy_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    product_in: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    product_out: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    # {what, why, data_used, thresholds, alternatives, diagnosis}
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmCall(Base):
    """Toda chamada de LLM registrada: custo, prompt, resposta."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
