"""Decision Engine em modo RECOMMEND (§8.1).

Só escreve em `ai_recommendations`. Não toca estado de produto, portfólio nem
orçamento — executar é outra camada (Fase 6), e o humano ainda decide.

Proteções que o motor respeita: INCONCLUSIVE e NO_DATA nunca viram
recomendação de troca; troca exige UNDERPERFORMER, que por sua vez exige
amostra madura e dado liquidado (ver `domain/zones.py`).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import formulas, zones
from app.domain.enums import DecisionType, PortfolioTier, ProductState, SettlementStatus
from app.domain.zones import Diagnosis, Zone, ZoneInput, ZoneThresholds
from app.models.ai import AiRecommendation
from app.models.metrics import PerformanceDaily
from app.services import portfolio_service
from app.services._funnel_queries import products_in_state
from app.services.opportunity_scoring import latest_score
from app.services.portfolio_service import PortfolioParams

ENGINE_VERSION = "engine_v1_recommend"

_SETTLEMENT_ORDER = {
    SettlementStatus.PROVISIONAL: 0,
    SettlementStatus.PARTIAL: 1,
    SettlementStatus.SETTLED: 2,
}


@dataclass
class AnalysisResult:
    sizing: dict
    zones: dict[str, int] = field(default_factory=dict)
    recommendations_created: int = 0
    recommendations_skipped_duplicate: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Aggregate:
    impressions: int | None
    clicks: int | None
    ad_spend: object
    revenue: object
    conversions: int | None
    revenue_data_available: bool
    settlement: SettlementStatus


def _aggregate(rows: list[PerformanceDaily]) -> _Aggregate:
    def total(attr: str):
        values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return sum(values) if values else None

    settlement = (
        min((r.settlement for r in rows), key=_SETTLEMENT_ORDER.__getitem__)
        if rows
        else SettlementStatus.PROVISIONAL
    )
    return _Aggregate(
        impressions=total("impressions"),
        clicks=total("clicks"),
        ad_spend=total("ad_spend"),
        revenue=total("revenue"),
        conversions=total("conversions"),
        revenue_data_available=any(r.revenue_data_available for r in rows),
        settlement=settlement,
    )


def _has_pending(db: Session, decision_type: DecisionType, subject_type: str, subject_id: str):
    return (
        db.execute(
            select(AiRecommendation.id).where(
                AiRecommendation.status == "PENDING",
                AiRecommendation.decision_type == decision_type,
                AiRecommendation.subject_type == subject_type,
                AiRecommendation.subject_id == subject_id,
            )
        ).first()
        is not None
    )


def analyze(
    db: Session, params: PortfolioParams, *, run_id: int | None = None
) -> AnalysisResult:
    sizing = portfolio_service.sizing(db, params)
    result = AnalysisResult(
        sizing={
            "data_available": sizing.data_available,
            "recommended_size": sizing.recommended_size,
            "range": [sizing.range_min, sizing.range_max],
            "exploration_slots": sizing.exploration_slots,
            "exploitation_slots": sizing.exploitation_slots,
            "days_to_decision": str(sizing.days_to_decision)
            if sizing.days_to_decision is not None
            else None,
            "feasible": sizing.feasible,
        },
        warnings=list(sizing.warnings),
    )

    def recommend(
        decision_type: DecisionType, subject_type: str, subject_id: str | None, rationale: dict
    ) -> None:
        if subject_id is not None and _has_pending(db, decision_type, subject_type, subject_id):
            result.recommendations_skipped_duplicate += 1
            return
        db.add(
            AiRecommendation(
                run_id=run_id,
                decision_type=decision_type,
                subject_type=subject_type,
                subject_id=subject_id,
                rationale={**rationale, "engine_version": ENGINE_VERSION},
            )
        )
        result.recommendations_created += 1

    entries = portfolio_service.active_entries(db)
    limits = ZoneThresholds(
        min_clicks=params.min_clicks_for_decision,
        min_impressions=params.min_impressions_for_decision,
        min_test_duration_days=params.min_test_duration_days,
    )
    today = datetime.now(UTC).date()
    zone_counts = dict.fromkeys(Zone, 0)

    for entry in entries:
        rows = list(
            db.execute(
                select(PerformanceDaily).where(
                    PerformanceDaily.product_id == entry.product_id,
                    PerformanceDaily.metric_date >= entry.entered_at.date(),
                )
            ).scalars()
        )
        agg = _aggregate(rows)
        roi = formulas.roi(agg.revenue, agg.ad_spend)
        zone = zones.classify(
            ZoneInput(
                clicks=agg.clicks,
                impressions=agg.impressions,
                roi=roi,
                revenue_data_available=agg.revenue_data_available,
                settlement=agg.settlement,
                days_in_test=(today - entry.entered_at.date()).days,
            ),
            limits,
        )
        zone_counts[zone] += 1

        if zone is not Zone.UNDERPERFORMER:
            continue

        ctr = formulas.ctr(agg.clicks, agg.impressions)
        cvr = formulas.cvr(agg.conversions, agg.clicks)
        diagnosis = zones.diagnose(ctr=ctr, cvr=cvr, roi=roi)
        data_used = {
            "clicks": agg.clicks,
            "impressions": agg.impressions,
            "ctr": str(ctr) if ctr is not None else None,
            "cvr": str(cvr) if cvr is not None else None,
            "roi": str(roi) if roi is not None else None,
            "settlement": agg.settlement.value,
        }
        # Criativo fraco se corrige trocando o criativo; trocar o produto seria erro de alvo.
        if diagnosis is Diagnosis.CREATIVE_WEAK:
            recommend(
                DecisionType.KEEP,
                "product",
                str(entry.product_id),
                {
                    "what": "manter o produto e trocar o criativo",
                    "why": "ROI negativo com CTR baixo aponta criativo/segmentação, não produto",
                    "diagnosis": diagnosis.value,
                    "data_used": data_used,
                },
            )
        else:
            recommend(
                DecisionType.REPLACE,
                "product",
                str(entry.product_id),
                {
                    "what": "substituir o produto",
                    "why": "ROI negativo com amostra madura e dado liquidado",
                    "diagnosis": diagnosis.value,
                    "replacement_hint": (
                        "buscar candidato com comissão acima da mediana"
                        if diagnosis is Diagnosis.COMMISSION_INSUFFICIENT
                        else "trocar o produto, manter o criativo"
                    ),
                    "data_used": data_used,
                },
            )

    result.zones = {zone.value: count for zone, count in zone_counts.items()}

    # Entradas novas: só vagas de exploração; ocupar exploração é como se coleta dado.
    active_exploration = sum(e.tier is PortfolioTier.EXPLORATION for e in entries)
    free_slots = min(
        sizing.exploration_slots - active_exploration,
        params.max_active_products - len(entries),
    )
    if free_slots > 0:
        in_portfolio = {e.product_id for e in entries}
        ranked = []
        for product in products_in_state(db, ProductState.CANDIDATE):
            score = latest_score(db, product.id)
            # Score indicativo não decide entrada.
            if product.id in in_portfolio or score is None or not score.data_available:
                continue
            ranked.append((score.score, product, score))
        ranked.sort(key=lambda item: (-item[0], item[1].id))

        for _, product, score in ranked[:free_slots]:
            recommend(
                DecisionType.PROMOTE,
                "product",
                str(product.id),
                {
                    "what": "colocar o candidato em teste (tier EXPLORATION)",
                    "why": f"{free_slots} vaga(s) de exploração livre; maior Opportunity Score",
                    "data_used": {
                        "opportunity_score": str(score.score),
                        "algorithm_version": score.algorithm_version,
                        "daily_test_budget": str(params.min_daily_test_budget),
                    },
                },
            )
    elif not sizing.feasible:
        result.warnings.append("sem vagas: o orçamento não sustenta nem o piso do portfólio")

    if sizing.recommended_size is not None and sizing.recommended_size != len(entries):
        recommend(
            DecisionType.RESIZE_PORTFOLIO,
            "portfolio",
            "portfolio",
            {
                "what": f"ajustar o portfólio para {sizing.recommended_size} produtos",
                "why": "tamanho que o orçamento e o CPC observado sustentam",
                "data_used": {"active_count": len(entries), "assumptions": sizing.assumptions},
            },
        )

    db.flush()
    return result
