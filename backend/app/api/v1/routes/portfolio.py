"""Portfólio e recomendações. Leitura e análise (RECOMMEND); nada executa aqui."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core.config import Settings, get_settings
from app.core.security import require_api_key, require_reader
from app.db.session import get_db
from app.domain import formulas
from app.domain.enums import SettlementStatus
from app.models.ai import AiRecommendation
from app.models.metrics import PerformanceDaily
from app.schemas.runs import RunResponse
from app.services import decision_engine, portfolio_service
from app.services.budget_guard import BudgetGuard

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", dependencies=[Depends(require_reader)])
def get_portfolio(db: Session = Depends(get_db)) -> dict:
    entries = portfolio_service.active_entries(db)
    return {
        "active_count": len(entries),
        "total_daily_budget": str(sum(e.allocated_daily_budget for e in entries)),
        "items": [
            {
                "product_id": e.product_id,
                "tier": e.tier.value,
                "entered_at": e.entered_at,
                "allocated_daily_budget": str(e.allocated_daily_budget),
            }
            for e in entries
        ],
    }


@router.get("/portfolio/sizing", dependencies=[Depends(require_reader)])
def get_sizing(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """calculateOptimalPortfolioSize(). RECOMMEND: calcula e não executa."""
    result = portfolio_service.sizing(db, portfolio_service.load_params(db, settings))
    body = asdict(result)
    body["days_to_decision"] = (
        str(result.days_to_decision) if result.days_to_decision is not None else None
    )
    return body


@router.get("/recommendations", dependencies=[Depends(require_reader)])
def list_recommendations(status: str = "PENDING", db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(AiRecommendation)
        .where(AiRecommendation.status == status)
        .order_by(AiRecommendation.id.desc())
        .limit(200)
    ).scalars()
    return {
        "items": [
            {
                "id": r.id,
                "decision_type": r.decision_type.value,
                "subject_type": r.subject_type,
                "subject_id": r.subject_id,
                "rationale": r.rationale,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }


@router.post("/portfolio/analyze", response_model=RunResponse)
def analyze_portfolio(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Roda o Decision Engine em modo RECOMMEND."""
    effective_dry_run = settings.dry_run if dry_run is None else dry_run
    params = portfolio_service.load_params(db, settings)

    def work() -> WorkOutcome:
        result = decision_engine.analyze(db, params)
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(
            summary=summary, items_processed=result.recommendations_created, warnings=warnings
        )

    return run_workflow(
        db, name="portfolio_analyze", owner=actor, dry_run=effective_dry_run, work=work
    )


@router.get("/budget/status", dependencies=[Depends(require_reader)])
def budget_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    """Teto, comprometido, realizado e disponível do dia."""
    return BudgetGuard(db, portfolio_service.load_params(db, settings)).status()


@router.get("/performance/daily", dependencies=[Depends(require_reader)])
def performance_daily(
    product_id: int | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
) -> dict:
    """Série diária. Campo ausente sai como null, nunca 0."""
    since = datetime.now(UTC).date() - timedelta(days=max(1, min(days, 365)) - 1)
    query = select(PerformanceDaily).where(PerformanceDaily.metric_date >= since)
    if product_id is not None:
        query = query.where(PerformanceDaily.product_id == product_id)
    rows = db.execute(
        query.order_by(PerformanceDaily.metric_date.desc(), PerformanceDaily.product_id)
    ).scalars()
    return {
        "items": [
            {
                "metric_date": r.metric_date,
                "product_id": r.product_id,
                "impressions": r.impressions,
                "clicks": r.clicks,
                "ad_spend": _num(r.ad_spend),
                "conversions": r.conversions,
                "revenue": _num(r.revenue),
                "roi": _num(r.roi),
                "roas": _num(r.roas),
                "cost_data_available": r.cost_data_available,
                "revenue_data_available": r.revenue_data_available,
                "settlement": r.settlement.value,
            }
            for r in rows
        ]
    }


@router.get("/performance/summary", dependencies=[Depends(require_reader)])
def performance_summary(days: int = 7, db: Session = Depends(get_db)) -> dict:
    """KPIs da janela. ROI só entra se houve custo e receita medidos no mesmo dia."""
    since = datetime.now(UTC).date() - timedelta(days=max(1, min(days, 365)) - 1)
    rows = list(
        db.execute(select(PerformanceDaily).where(PerformanceDaily.metric_date >= since)).scalars()
    )
    measured = [r for r in rows if r.cost_data_available and r.revenue_data_available]
    spend = sum((r.ad_spend for r in measured if r.ad_spend is not None), Decimal(0))
    revenue = sum((r.revenue for r in measured if r.revenue is not None), Decimal(0))
    return {
        "window_days": days,
        "rows": len(rows),
        "measured_rows": len(measured),
        "ad_spend": _num(spend) if measured else None,
        "revenue": _num(revenue) if measured else None,
        "profit": _num(formulas.profit(revenue, spend)) if measured else None,
        "roi": _num(formulas.roi(revenue, spend)) if measured else None,
        "settled_rows": sum(r.settlement is SettlementStatus.SETTLED for r in rows),
    }


def _num(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
