"""Gatilhos do funil consumidos pelo n8n (workflow 01 e 02).

Sem regra de negócio aqui: autentica, resolve o modo e delega ao serviço.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adapters.marketplace.registry import get_marketplace_adapter
from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_db
from app.schemas.runs import DiscoveryRequest, RunResponse
from app.services import discovery_service, opportunity_scoring, qualification_service

router = APIRouter(prefix="/trigger", tags=["triggers"], dependencies=[Depends(require_api_key)])


def _resolve_dry_run(dry_run: bool | None, settings: Settings) -> bool:
    """`?dry_run=` explícito vence; sem ele vale o DRY_RUN global."""
    return settings.dry_run if dry_run is None else dry_run


@router.post("/discovery", response_model=RunResponse)
def trigger_discovery(
    body: DiscoveryRequest | None = None,
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    request = body or DiscoveryRequest()
    adapter = get_marketplace_adapter(settings)

    def work() -> WorkOutcome:
        result = discovery_service.run_discovery(
            db, adapter, keyword=request.keyword, limit=request.limit
        )
        return WorkOutcome(summary=asdict(result), items_processed=result.fetched)

    return run_workflow(
        db,
        name="discovery",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/qualification", response_model=RunResponse)
def trigger_qualification(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    def work() -> WorkOutcome:
        result = qualification_service.run_qualification(db)
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(summary=summary, items_processed=result.evaluated, warnings=warnings)

    return run_workflow(
        db,
        name="qualification",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/scoring/opportunity", response_model=RunResponse)
def trigger_opportunity_scoring(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    def work() -> WorkOutcome:
        result = opportunity_scoring.run_opportunity_scoring(db)
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(summary=summary, items_processed=result.scored, warnings=warnings)

    return run_workflow(
        db,
        name="opportunity_scoring",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/candidates/promote", response_model=RunResponse)
def trigger_candidate_promotion(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    def work() -> WorkOutcome:
        result = opportunity_scoring.run_promotion(db)
        return WorkOutcome(summary=asdict(result), items_processed=result.evaluated)

    return run_workflow(
        db,
        name="candidate_promotion",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )
