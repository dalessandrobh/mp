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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import RunStatus
from app.models._types import run_status_enum


class ConfigParameter(Base):
    """Parâmetros vivos, editáveis pelo dashboard e recomendáveis pela IA.

    `min_value`/`max_value` são limites duros: a IA pode recomendar dentro deles,
    nunca fora.
    """

    __tablename__ = "config_parameters"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[dict | None] = mapped_column(JSONB)
    max_value: Mapped[dict | None] = mapped_column(JSONB)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ai_adjustable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfigParameterHistory(Base):
    __tablename__ = "config_parameter_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ai_decisions.id"))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BudgetLedger(Base):
    """Razão contábil do orçamento.

    Não dá para reservar gasto atomicamente no Meta, então mantemos o
    compromisso planejado (COMMITMENT) e o gasto real (ACTUAL) aqui. O
    BudgetGuard valida contra a soma dos dois.
    """

    __tablename__ = "budget_ledger"
    __table_args__ = (Index("ix_budget_ledger_ledger_date_scope", "ledger_date", "scope"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ledger_date: Mapped[date] = mapped_column(Date, nullable=False)
    # 'COMMITMENT' | 'ACTUAL' | 'RELEASE'
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    # 'GLOBAL' | 'EXPLORATION' | 'EXPLOITATION'
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("campaigns.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ai_decisions.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 'INFO' | 'WARNING' | 'CRITICAL' | 'ABORT'
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    acknowledged_by: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowRun(Base):
    """Uma linha por execução de workflow do n8n. Base de observabilidade."""

    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_name: Mapped[str] = mapped_column(Text, nullable=False)
    n8n_execution_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RunStatus] = mapped_column(
        run_status_enum, nullable=False, server_default="RUNNING"
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_processed: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSONB)


class IdempotencyKey(Base):
    """Proteção contra retry do n8n criando efeitos duplicados."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    status_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionLock(Base):
    """Proteção contra execuções concorrentes do mesmo workflow."""

    __tablename__ = "execution_locks"

    lock_name: Mapped[str] = mapped_column(Text, primary_key=True)
    acquired_by: Mapped[str] = mapped_column(Text, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Explicita que são ESTIMATIVAS, não previsões.
    assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
