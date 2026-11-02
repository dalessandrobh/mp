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


class ExpectedValue(Base):
    """Valor esperado de comissão por clique (ev_v1). Append-only e versionado.

    Tabela própria, e não uma coluna em `opportunity_scores`, porque a unidade é outra:
    `opp_v2` dá 0 a 100 e `ev_v1` dá reais por clique. Guardar os dois na mesma coluna
    faria o corte de promoção (`PROMOTION_MIN_OPPORTUNITY_SCORE = 50`) comparar score com
    dinheiro e nunca promover ninguém.

    `alpha`/`beta` são a posterior Beta da taxa de conversão; ficam gravados porque é deles
    que o Thompson sampling vai sortear quando a Fase 2 chegar (docs/plano-10k.md §3.4).
    """

    __tablename__ = "expected_values"
    __table_args__ = (
        Index("ix_expected_values_product_id_computed_at", "product_id", "computed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    # Receita esperada por clique: comissão em dinheiro × taxa de conversão estimada.
    ev_per_click: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    # `r` da fórmula: exato, vem da API.
    commission_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cvr_estimate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    # Quantil 10%: decide manter ou cortar. Quantil 90%: decide o que testar.
    cvr_lower: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvr_upper: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    alpha: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    beta: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    prior_source: Mapped[str] = mapped_column(Text, nullable=False)
    # Momento relativo medido na série de snapshots; None quando a série é curta demais.
    momentum: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # false => a estimativa ainda é prior, sem nenhum clique próprio por trás.
    data_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
