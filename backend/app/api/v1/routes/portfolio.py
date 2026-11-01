"""Portfólio e recomendações. Leitura e análise (RECOMMEND); nada executa aqui."""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core.config import Settings, get_settings
from app.core.security import require_api_key, require_reader
from app.db.session import get_db
from app.models.ai import AiRecommendation
from app.schemas.runs import RunResponse
from app.services import decision_engine, portfolio_service

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
