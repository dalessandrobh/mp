"""Gatilhos do funil consumidos pelo n8n (workflow 01 e 02).

Sem regra de negócio aqui: autentica, resolve o modo e delega ao serviço.
"""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.adapters.ads.registry import get_ads_adapter
from app.adapters.llm.registry import get_llm_adapter
from app.adapters.marketplace.registry import get_marketplace_adapter
from app.adapters.social.registry import get_social_adapter
from app.api.v1.routes._runner import WorkOutcome, run_workflow
from app.core import idempotency
from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.security import require_api_key
from app.db.session import SessionLocal, get_db
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
    alert_rules,
    config_params,
    consolidation_service,
    content_service,
    daily_report,
    discovery_service,
    ev_scoring,
    ingestion_service,
    oauth_store,
    opportunity_scoring,
    performance_scoring,
    portfolio_service,
    publishing_service,
    qualification_service,
    tracking_service,
)
from app.services.ads_creation_service import create_campaigns
from app.services.ads_gateway import AdsGateway, ExecutionContext, GatewayLimits
from app.services.budget_guard import BudgetGuard
from app.services.pinterest_ads_targets import PinterestAdTargets

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
        if request.by_commission:
            by_com = discovery_service.run_commission_discovery(
                db,
                adapter,
                per_category=request.sweep_size(settings.commission_sweep_per_category),
                min_commission_value=(
                    request.min_commission_value
                    if request.min_commission_value is not None
                    else settings.commission_sweep_min_value
                ),
                min_sales=(
                    request.min_sales
                    if request.min_sales is not None
                    else settings.commission_sweep_min_sales
                ),
                category_ids=request.category_ids,
            )
            warnings = [f"categoria {c} falhou na leitura" for c in by_com.failed]
            return WorkOutcome(
                summary=asdict(by_com), items_processed=by_com.kept, warnings=warnings
            )
        if request.by_category:
            by_cat = discovery_service.run_category_discovery(
                db,
                adapter,
                per_category=request.per_category,
                category_ids=request.category_ids,
            )
            warnings = [f"categoria {c} falhou na leitura" for c in by_cat.failed]
            return WorkOutcome(
                summary=asdict(by_cat), items_processed=by_cat.fetched, warnings=warnings
            )
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


@router.post("/scoring/ev", response_model=RunResponse)
def trigger_ev_scoring(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Receita esperada por clique. Roda depois do Opportunity Score e do sync de vendas:
    precisa do último snapshot e do clique medido para a evidência própria entrar."""

    def work() -> WorkOutcome:
        result = ev_scoring.run_ev_scoring(db)
        summary = asdict(result)
        warnings = summary.pop("warnings")
        return WorkOutcome(summary=summary, items_processed=result.scored, warnings=warnings)

    return run_workflow(
        db,
        name="ev_scoring",
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
    ads_adapter = get_ads_adapter(
        settings,
        token_store=oauth_store.TokenStore(
            db, SessionLocal, seed_refresh_token=settings.pinterest_refresh_token
        ),
    )
    gateway = AdsGateway(db, ads_adapter, BudgetGuard(db, params), limits, ExecutionContext())
    # O Pinterest promove um pin que já existe; o mock e o Meta seguem o caminho original.
    targets = None
    if not settings.mock_ads and settings.ads_provider == "pinterest":
        targets = PinterestAdTargets(
            db,
            get_marketplace_adapter(settings),
            public_base=settings.public_base,
            max_sub_id_length=settings.subid_max_length,
            max_cpc=settings.pinterest_ads_max_cpc,
        )

    def work() -> WorkOutcome:
        result = create_campaigns(db, gateway, params, targets)
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
    ads_adapter = get_ads_adapter(
        settings,
        token_store=oauth_store.TokenStore(
            db, SessionLocal, seed_refresh_token=settings.pinterest_refresh_token
        ),
    )
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


@router.post("/portfolio/snapshot", response_model=RunResponse)
def trigger_portfolio_snapshot(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Fotografia diária do portfólio. Repetir no mesmo dia sobrescreve a do dia."""
    params = portfolio_service.load_params(db, settings)

    def work() -> WorkOutcome:
        snapshot = portfolio_service.take_snapshot(db, params)
        return WorkOutcome(
            summary={
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "active_count": snapshot.active_count,
                "winner_count": snapshot.winner_count,
                "total_daily_budget": str(snapshot.total_daily_budget),
            },
            items_processed=1,
        )

    return run_workflow(
        db,
        name="portfolio_snapshot",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/alerts/evaluate", response_model=RunResponse)
def trigger_alert_evaluation(
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Avalia as regras de alerta. `items` traz só os alertas NOVOS, para o n8n notificar."""
    params = portfolio_service.load_params(db, settings)
    max_unreviewed = config_params.get_int(
        db, "MAX_UNREVIEWED_CAMPAIGNS", settings.max_unreviewed_campaigns
    )

    def work() -> WorkOutcome:
        result = alert_rules.evaluate(db, params, max_unreviewed=max_unreviewed)
        return WorkOutcome(
            summary={
                "created": len(result.created),
                "skipped_duplicates": result.skipped_duplicates,
            },
            items=result.created,
            items_processed=len(result.created),
        )

    # Alerta é o próprio registro da avaliação: dry-run não grava, mas devolve o que gravaria.
    return run_workflow(
        db,
        name="alerts_evaluation",
        owner=actor,
        dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/report/daily", response_model=RunResponse)
def trigger_daily_report(
    day: str | None = None,
    dry_run: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Monta o resumo do dia. `summary.message` é o texto pronto para o WhatsApp."""
    params = portfolio_service.load_params(db, settings)
    try:
        wanted = date.fromisoformat(day) if day else None
    except ValueError as exc:
        raise DomainError("day deve ser YYYY-MM-DD") from exc

    def work() -> WorkOutcome:
        report = daily_report.build(db, settings, params, day=wanted)
        return WorkOutcome(summary={"message": report.message, **report.data}, items_processed=1)

    return run_workflow(
        db, name="daily_report", owner=actor, dry_run=_resolve_dry_run(dry_run, settings),
        work=work,
    )


@router.post("/content/generate", response_model=RunResponse)
def trigger_content_generation(
    dry_run: bool | None = None,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Pacote diário de conteúdo orgânico. `items[]` = um post pronto (foto + legenda + link)."""
    if not idempotency_key:
        raise DomainError("Header Idempotency-Key é obrigatório neste endpoint")

    effective_dry_run = _resolve_dry_run(dry_run, settings)
    fingerprint = {"dry_run": effective_dry_run}
    stored = idempotency.lookup(
        db, key=idempotency_key, endpoint="content/generate", payload=fingerprint
    )
    if stored is not None:
        return RunResponse(**stored)

    adapter = get_marketplace_adapter(settings)
    llm = get_llm_adapter(settings)

    def work() -> WorkOutcome:
        # O post precisa de um link rastreado, e gerar link é ação de nível 3.
        if not autonomy.permits(settings.ai_autonomy_level, ActionClass.GENERATE_LINKS):
            return _skipped_by_autonomy(settings, ActionClass.GENERATE_LINKS)
        result = content_service.generate_daily_package(
            db, adapter, llm, count=settings.content_daily_count,
            max_sub_id_length=settings.subid_max_length,
            llm_cap_usd=settings.llm_daily_cost_cap_usd,
            public_base=settings.public_base,
        )
        summary = {
            "created": result.created, "llm_used": result.llm_used,
            "template_used": result.template_used, "skipped": result.skipped,
            "llm_configured": llm is not None,
        }
        return WorkOutcome(
            summary=summary, items_processed=result.created, items=result.packages,
            warnings=result.warnings,
        )

    response = run_workflow(
        db, name="content_generation", owner=actor, dry_run=effective_dry_run, work=work
    )
    if not effective_dry_run:
        idempotency.store(
            db, key=idempotency_key, endpoint="content/generate", payload=fingerprint,
            response_body=response.model_dump(),
        )
    return response


@router.post("/content/publish", response_model=RunResponse)
def trigger_content_publish(
    dry_run: bool | None = None,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_api_key),
) -> RunResponse:
    """Publica os criativos do dia na rede social. Roda DEPOIS de content/generate.

    Primeira ação do MP que fica pública: exige autonomia 4 (PUBLISH_ORGANIC). Em DRY_RUN
    o rascunho é montado e registrado em social_posts com status DRY_RUN, sem tocar a rede
    — serve para conferir texto, link e truncamento antes de valer.
    """
    if not idempotency_key:
        raise DomainError("Header Idempotency-Key é obrigatório neste endpoint")

    effective_dry_run = _resolve_dry_run(dry_run, settings)
    fingerprint = {"dry_run": effective_dry_run}
    stored = idempotency.lookup(
        db, key=idempotency_key, endpoint="content/publish", payload=fingerprint
    )
    if stored is not None:
        return RunResponse(**stored)

    marketplace = get_marketplace_adapter(settings)
    social = get_social_adapter(
        settings,
        token_store=oauth_store.TokenStore(
            db, SessionLocal, seed_refresh_token=settings.pinterest_refresh_token
        ),
    )

    def work() -> WorkOutcome:
        if not autonomy.permits(settings.ai_autonomy_level, ActionClass.PUBLISH_ORGANIC):
            return _skipped_by_autonomy(settings, ActionClass.PUBLISH_ORGANIC)
        result = publishing_service.publish_pending(
            db,
            social,
            marketplace,
            public_base=settings.public_base,
            max_sub_id_length=settings.subid_max_length,
            max_per_run=settings.publish_max_per_run,
            dry_run=effective_dry_run,
            price_ceiling=float(settings.publish_price_ceiling),
            brand_categories=settings.brand_categories,
        )
        summary = {
            "considered": result.considered, "published": result.published,
            "dry_run": result.dry_run, "blocked": result.blocked,
            "failed": result.failed, "network": social.code,
            # O que o dono precisa olhar: criativos sem decisão, e onde decidir.
            "awaiting_approval": result.awaiting_approval,
            "queue_url": f"{settings.public_base}/publicacao" if settings.public_base else None,
        }
        return WorkOutcome(
            summary=summary,
            items_processed=result.published + result.dry_run,
            items=result.posts,
            warnings=result.warnings,
        )

    response = run_workflow(
        db, name="content_publish", owner=actor, dry_run=effective_dry_run, work=work
    )
    if not effective_dry_run:
        idempotency.store(
            db, key=idempotency_key, endpoint="content/publish", payload=fingerprint,
            response_body=response.model_dump(),
        )
    return response
