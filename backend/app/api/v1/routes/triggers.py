"""Gatilhos do funil consumidos pelo n8n (workflow 01 e 02).

Sem regra de negócio aqui: autentica, resolve o modo e delega ao serviço.
"""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.adapters.ads.registry import get_ads_adapter
from app.adapters.marketplace.registry import get_marketplace_adapter
from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core import idempotency
from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.security import require_api_key
from app.db.session import get_db
from app.domain import autonomy
from app.domain.autonomy import ActionClass
from app.domain.enums import RunStatus
from app.schemas.runs import (
    DiscoveryRequest,
    LinkGenerationRequest,
    PerformanceWindowRequest,
    RunResponse,
)
from app.services import (
    config_params,
    consolidation_service,
    discovery_service,
    ingestion_service,
    opportunity_scoring,
    performance_scoring,
    portfolio_service,
    qualification_service,
    tracking_service,
)
from app.services.ads_creation_service import create_campaigns
from app.services.ads_gateway import AdsGateway, ExecutionContext, GatewayLimits
from app.services.budget_guard import BudgetGuard

router = APIRouter(prefix="/trigger", tags=["triggers"], dependencies=[Depends(require_api_key)])


def _resolve_dry_run(dry_run: bool | None, settings: Settings) -> bool:
    """`?dry_run=` explícito vence; sem ele vale o DRY_RUN global."""
    return settings.dry_run if dry_run is None else dry_run


def _skipped_by_autonomy(settings: Settings, action: ActionClass) -> WorkOutcome:
    return WorkOutcome(
        summary={"skipped": "autonomy"},
        status=RunStatus.SKIPPED,
        warnings=[autonomy.refusal(settings.ai_autonomy_level, action)],
    )


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
        if not autonomy.permits(settings.ai_autonomy_level, ActionClass.PROMOTE_CANDIDATE):
            return _skipped_by_autonomy(settings, ActionClass.PROMOTE_CANDIDATE)
        result = opportunity_scoring.run_promotion(db)
        return WorkOutcome(summary=asdict(result), items_processed=result.evaluated)

    return run_workflow(
        db,
        name="candidate_promotion",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/links/generate", response_model=RunResponse)
def trigger_link_generation(
    body: LinkGenerationRequest | None = None,
    dry_run: bool | None = None,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    if not idempotency_key:
        raise DomainError("Header Idempotency-Key é obrigatório neste endpoint")

    request = body or LinkGenerationRequest()
    effective_dry_run = _resolve_dry_run(dry_run, settings)
    fingerprint = {**request.model_dump(), "dry_run": effective_dry_run}

    stored = idempotency.lookup(
        db, key=idempotency_key, endpoint="links/generate", payload=fingerprint
    )
    if stored is not None:
        return RunResponse(**stored)

    adapter = get_marketplace_adapter(settings)

    def work() -> WorkOutcome:
        if not autonomy.permits(settings.ai_autonomy_level, ActionClass.GENERATE_LINKS):
            return _skipped_by_autonomy(settings, ActionClass.GENERATE_LINKS)
        result = tracking_service.generate_links(
            db,
            adapter,
            channel=request.channel,
            max_sub_id_length=settings.subid_max_length,
            campaign_id=request.campaign_id,
            creative_id=request.creative_id,
        )
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(summary=summary, items_processed=result.created, warnings=warnings)

    response = run_workflow(
        db, name="link_generation", owner=actor, dry_run=effective_dry_run, work=work
    )
    # Dry-run não grava a chave: repetir a chamada de verdade tem de executar.
    if not effective_dry_run:
        idempotency.store(
            db,
            key=idempotency_key,
            endpoint="links/generate",
            payload=fingerprint,
            response_body=response.model_dump(),
        )
    return response


@router.post("/ads/create", response_model=RunResponse)
def trigger_ads_creation(
    dry_run: bool | None = None,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Cria Campaign/AdSet/Ad sempre PAUSED. A ativação é humana, no Meta."""
    if not idempotency_key:
        raise DomainError("Header Idempotency-Key é obrigatório neste endpoint")

    effective_dry_run = _resolve_dry_run(dry_run, settings)
    fingerprint = {"dry_run": effective_dry_run}
    stored = idempotency.lookup(db, key=idempotency_key, endpoint="ads/create", payload=fingerprint)
    if stored is not None:
        return RunResponse(**stored)

    params = portfolio_service.load_params(db, settings)
    limits = GatewayLimits(
        max_unreviewed=config_params.get_int(
            db, "MAX_UNREVIEWED_CAMPAIGNS", settings.max_unreviewed_campaigns
        ),
        max_per_execution=config_params.get_int(
            db, "MAX_CAMPAIGNS_PER_EXECUTION", settings.max_campaigns_per_execution
        ),
        dry_run=effective_dry_run,
        autonomy_level=settings.ai_autonomy_level,
    )
    gateway = AdsGateway(
        db, get_ads_adapter(settings), BudgetGuard(db, params), limits, ExecutionContext()
    )

    def work() -> WorkOutcome:
        result = create_campaigns(db, gateway, params)
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(
            summary=summary,
            items_processed=result.created,
            status=RunStatus.ABORTED if result.aborted else RunStatus.SUCCESS,
            warnings=warnings,
        )

    response = run_workflow(
        db, name="ads_creation", owner=actor, dry_run=effective_dry_run, work=work
    )
    if not effective_dry_run:
        idempotency.store(
            db,
            key=idempotency_key,
            endpoint="ads/create",
            payload=fingerprint,
            response_body=response.model_dump(),
        )
    return response


@router.post("/performance/sync", response_model=RunResponse)
def trigger_performance_sync(
    body: PerformanceWindowRequest | None = None,
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Traz Meta Insights e os dois relatórios de conversão. Só ingere, não calcula."""
    request = body or PerformanceWindowRequest()
    until = datetime.now(UTC).date()
    since = until - timedelta(days=request.days - 1)
    ads_adapter = get_ads_adapter(settings)
    marketplace_adapter = get_marketplace_adapter(settings)

    def work() -> WorkOutcome:
        marketplace = discovery_service.ensure_marketplace(db, marketplace_adapter)
        ad_rows = ingestion_service.sync_ad_metrics(db, ads_adapter, since=since, until=until)
        conversions = ingestion_service.sync_conversions(
            db, marketplace_adapter, marketplace=marketplace, since=since, until=until
        )
        summary = {
            # A janela é o que prova cobertura na consolidação: receita 0 só vale dentro dela.
            "window": {"since": since.isoformat(), "until": until.isoformat()},
            "ad_metric_rows": ad_rows,
            **asdict(conversions),
        }
        return WorkOutcome(summary=summary, items_processed=ad_rows + conversions.conversions_new)

    return run_workflow(
        db,
        name=consolidation_service.SYNC_WORKFLOW,
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/performance/consolidate", response_model=RunResponse)
def trigger_performance_consolidation(
    body: PerformanceWindowRequest | None = None,
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """`*_raw` -> `performance_daily`, depois Performance Score."""
    request = body or PerformanceWindowRequest(days=30)
    until = datetime.now(UTC).date()
    since = until - timedelta(days=request.days - 1)
    params = portfolio_service.load_params(db, settings)

    def work() -> WorkOutcome:
        daily = consolidation_service.consolidate(db, since=since, until=until)
        scores = performance_scoring.run_performance_scoring(db, params)
        daily_summary = asdict(daily)
        score_summary = asdict(scores)
        warnings = daily_summary.pop("warnings") + score_summary.pop("warnings")
        return WorkOutcome(
            summary={"daily": daily_summary, "scores": score_summary},
            items_processed=daily.rows_created + daily.rows_updated,
            warnings=warnings,
        )

    return run_workflow(
        db,
        name="performance_consolidation",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )
