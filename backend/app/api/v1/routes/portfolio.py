"""Portfólio e recomendações. Leitura e análise (RECOMMEND); nada executa aqui."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core import idempotency
from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError, NotFound
from app.core.security import require_api_key, require_dashboard_user, require_reader
from app.db.session import get_db
from app.domain import formulas
from app.domain.enums import SettlementStatus
from app.models.ai import AiDecision, AiRecommendation
from app.models.metrics import PerformanceDaily
from app.schemas.runs import RejectRequest, RunResponse
from app.services import decision_engine, execution_service, portfolio_service
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


def _execution_context(
    db: Session,
    settings: Settings,
    *,
    actor: str,
    dry_run: bool,
    human_approved: bool,
    run_id: int | None = None,
) -> execution_service.ExecutionContext:
    params = portfolio_service.load_params(db, settings)
    return execution_service.ExecutionContext(
        params=params,
        guard=BudgetGuard(db, params),
        autonomy_level=settings.ai_autonomy_level,
        dry_run=dry_run,
        actor=actor,
        human_approved=human_approved,
        run_id=run_id,
    )


@router.post("/portfolio/apply", response_model=RunResponse)
def apply_recommendations(
    dry_run: bool | None = None,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Executa as recomendações que a autonomia atual permite. Resto fica PENDING."""
    if not idempotency_key:
        raise DomainError("Header Idempotency-Key é obrigatório neste endpoint")

    effective_dry_run = settings.dry_run if dry_run is None else dry_run
    fingerprint = {"dry_run": effective_dry_run}
    stored = idempotency.lookup(
        db, key=idempotency_key, endpoint="portfolio/apply", payload=fingerprint
    )
    if stored is not None:
        return RunResponse(**stored)

    def work() -> WorkOutcome:
        ctx = _execution_context(
            db, settings, actor="ai_engine", dry_run=effective_dry_run, human_approved=False
        )
        pending = db.execute(
            select(AiRecommendation)
            .where(AiRecommendation.status == "PENDING")
            .order_by(AiRecommendation.id)
        ).scalars().all()

        counts: dict[str, int] = {}
        items: list = []
        acted = 0
        for rec in pending:
            if acted >= settings.max_decisions_per_execution:
                counts["DEFERRED_LIMIT"] = counts.get("DEFERRED_LIMIT", 0) + 1
                continue
            outcome = execution_service.execute(db, rec, ctx)
            counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
            items.append(
                {
                    "recommendation_id": outcome.recommendation_id,
                    "status": outcome.status.value,
                    "detail": outcome.detail,
                    "decision_id": outcome.decision_id,
                }
            )
            if outcome.status in (
                execution_service.ExecutionStatus.EXECUTED,
                execution_service.ExecutionStatus.SIMULATED,
            ):
                acted += 1

        warnings = [
            f"rec {i['recommendation_id']}: {i['detail']}"
            for i in items
            if i["status"] in ("BLOCKED", "SKIPPED_AUTONOMY", "EXPIRED") and i["detail"]
        ]
        return WorkOutcome(
            summary={
                "pending": len(pending),
                "autonomy_level": settings.ai_autonomy_level,
                **counts,
            },
            items=items,
            items_processed=acted,
            warnings=sorted(set(warnings)),
        )

    response = run_workflow(
        db,
        name="portfolio_apply",
        owner=actor,
        dry_run=effective_dry_run,
        work=work,
        rollback_on_dry_run=False,
    )
    if not effective_dry_run:
        idempotency.store(
            db,
            key=idempotency_key,
            endpoint="portfolio/apply",
            payload=fingerprint,
            response_body=response.model_dump(),
        )
    return response


@router.post("/recommendations/{recommendation_id}/approve")
def approve_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: str = Depends(require_dashboard_user),
) -> dict:
    """Humano aprova: RECOMMEND vira EXECUTE. Dispensa o nível, não as travas de dado."""
    rec = _pending_recommendation(db, recommendation_id)
    informational = rec.rationale.get("action") not in execution_service.PLANNERS

    rec.status = "APPROVED"
    rec.reviewed_by = user
    rec.reviewed_at = datetime.now(UTC)

    if informational:
        db.flush()
        return {"id": rec.id, "status": "APPROVED", "executed": False}

    outcome = execution_service.execute(
        db,
        rec,
        _execution_context(db, settings, actor=user, dry_run=False, human_approved=True),
    )
    if outcome.status is not execution_service.ExecutionStatus.EXECUTED:
        # Não fica "aprovada" uma coisa que não aconteceu; e desfazemos aqui mesmo, sem
        # depender do rollback do get_db.
        if rec.status == "APPROVED":
            rec.status = "PENDING"
            rec.reviewed_by = None
            rec.reviewed_at = None
            db.flush()
        raise execution_service.ExecutionBlocked(
            f"Aprovação não executada ({outcome.status.value}): {outcome.detail}",
            details={"status": outcome.status.value},
        )
    return {
        "id": rec.id,
        "status": "EXECUTED",
        "executed": True,
        "decision_id": outcome.decision_id,
    }


@router.post("/recommendations/{recommendation_id}/reject")
def reject_recommendation(
    recommendation_id: int,
    body: RejectRequest | None = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_dashboard_user),
) -> dict:
    rec = _pending_recommendation(db, recommendation_id)
    rec.status = "REJECTED"
    rec.reviewed_by = user
    rec.reviewed_at = datetime.now(UTC)
    if body and body.reason:
        rec.rationale = {**rec.rationale, "rejection_reason": body.reason}
    db.flush()
    return {"id": rec.id, "status": "REJECTED"}


def _pending_recommendation(db: Session, recommendation_id: int) -> AiRecommendation:
    rec = db.get(AiRecommendation, recommendation_id)
    if rec is None:
        raise NotFound(f"recomendação {recommendation_id} não existe")
    if rec.status != "PENDING":
        raise DomainError(f"recomendação já está {rec.status}", details={"status": rec.status})
    return rec


@router.get("/decisions", dependencies=[Depends(require_reader)])
def list_decisions(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(AiDecision).order_by(AiDecision.id.desc()).limit(max(1, min(limit, 500)))
    ).scalars()
    return {
        "items": [
            {
                "id": d.id,
                "mode": d.mode.value,
                "decision_type": d.decision_type.value,
                "autonomy_level": d.autonomy_level,
                "dry_run": d.dry_run,
                "product_in": d.product_in,
                "product_out": d.product_out,
                "payload": d.payload,
                "created_at": d.created_at,
            }
            for d in rows
        ]
    }
