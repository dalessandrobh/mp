"""Importa todos os models para que o Alembic enxergue o metadata completo."""

from app.db.base import Base
from app.models.ads import Ad, AdSet, Campaign
from app.models.ai import AiDecision, AiRecommendation, LlmCall
from app.models.catalog import Marketplace, Product, ProductSnapshot
from app.models.content import Creative
from app.models.control import (
    Alert,
    AuditLog,
    BudgetLedger,
    ConfigParameter,
    ConfigParameterHistory,
    ExecutionLock,
    IdempotencyKey,
    Simulation,
    WorkflowRun,
)
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.metrics import (
    AdMetricsRaw,
    ConversionRaw,
    PerformanceDaily,
    PerformanceDailyRevision,
)
from app.models.portfolio import PortfolioProduct, PortfolioSnapshot
from app.models.scoring import OpportunityScore, PerformanceScore
from app.models.tracking import AffiliateLink

__all__ = [
    "Ad",
    "AdMetricsRaw",
    "AdSet",
    "AffiliateLink",
    "AiDecision",
    "AiRecommendation",
    "Alert",
    "AuditLog",
    "Base",
    "BudgetLedger",
    "Campaign",
    "ConfigParameter",
    "ConfigParameterHistory",
    "ConversionRaw",
    "Creative",
    "ExecutionLock",
    "IdempotencyKey",
    "LlmCall",
    "Marketplace",
    "OpportunityScore",
    "PerformanceDaily",
    "PerformanceDailyRevision",
    "PerformanceScore",
    "PortfolioProduct",
    "PortfolioSnapshot",
    "Product",
    "ProductCurrentState",
    "ProductSnapshot",
    "ProductStateTransition",
    "Simulation",
    "WorkflowRun",
]
