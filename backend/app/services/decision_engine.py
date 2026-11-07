"""Decision Engine em modo RECOMMEND (§8.1).

Só escreve em `ai_recommendations`. Não toca estado de produto, portfólio nem
orçamento — executar é outra camada (Fase 6), e o humano ainda decide.

Proteções que o motor respeita: INCONCLUSIVE e NO_DATA nunca viram
recomendação de troca; troca exige UNDERPERFORMER, que por sua vez exige
amostra madura e dado liquidado (ver `domain/zones.py`).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import brand_risk, formulas, zones
from app.domain.enums import DecisionType, PortfolioTier, ProductState, SettlementStatus
from app.domain.state_machine import get_current_state
from app.domain.zones import Diagnosis, Zone, ZoneInput, ZoneThresholds
from app.models.ai import AiRecommendation
from app.models.catalog import Product
from app.models.metrics import PerformanceDaily
from app.models.portfolio import PortfolioProduct
from app.services import category_quota, ev_scoring, portfolio_service
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
    held_category_quota: int = 0
    # Candidatos barrados pelo guarda de réplica na entrada do portfólio.
    held_brand_risk: int = 0
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


@dataclass(frozen=True)
class EntryEvaluation:
    zone: Zone
    diagnosis: Diagnosis | None
    data_used: dict


def evaluate_entry(
    db: Session, entry: PortfolioProduct, params: PortfolioParams, *, today=None
) -> EntryEvaluation:
    """Zona e diagnóstico de um produto do portfólio, com o dado de AGORA.

    A camada EXECUTE chama isto de novo antes de agir: a recomendação pode ter
    horas, e o dado maduro de ontem pode ter sido revisado hoje.
    """
    today = today or datetime.now(UTC).date()
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
        ZoneThresholds(
            min_clicks=params.min_clicks_for_decision,
            min_impressions=params.min_impressions_for_decision,
            min_test_duration_days=params.min_test_duration_days,
        ),
    )
    ctr = formulas.ctr(agg.clicks, agg.impressions)
    cvr = formulas.cvr(agg.conversions, agg.clicks)
    return EntryEvaluation(
        zone=zone,
        diagnosis=zones.diagnose(ctr=ctr, cvr=cvr, roi=roi)
        if zone is Zone.UNDERPERFORMER
        else None,
        data_used={
            "clicks": agg.clicks,
            "impressions": agg.impressions,
            "ctr": str(ctr) if ctr is not None else None,
            "cvr": str(cvr) if cvr is not None else None,
            "roi": str(roi) if roi is not None else None,
            "settlement": agg.settlement.value,
            "zone": zone.value,
        },
    )


def analyze(
    db: Session,
    params: PortfolioParams,
    *,
    run_id: int | None = None,
    entry_guard: Callable[[Product], brand_risk.RiskVerdict] | None = None,
) -> AnalysisResult:
    """`entry_guard` barra na ENTRADA do portfólio o produto suspeito de réplica.

    Sem ele a vaga de teste seria ocupada por um produto que a publicação barraria — e, como
    o pacote diário é postado à mão, o guarda da publicação nem chegaria a vê-lo. Barrar na
    entrada garante que toda vaga é de um produto que se pode divulgar.
    """
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
    today = datetime.now(UTC).date()
    zone_counts = dict.fromkeys(Zone, 0)

    for entry in entries:
        evaluation = evaluate_entry(db, entry, params, today=today)
        zone_counts[evaluation.zone] += 1

        if evaluation.zone is Zone.WINNER and entry.tier is PortfolioTier.EXPLORATION:
            product_state = get_current_state(db, entry.product_id)
            if product_state is ProductState.TEST:
                recommend(
                    DecisionType.PROMOTE,
                    "product",
                    str(entry.product_id),
                    {
                        "action": "GRADUATE",
                        "what": "graduar de TEST para ACTIVE (tier EXPLOITATION)",
                        "why": "ROI estável acima do corte de vencedor com amostra madura",
                        "data_used": evaluation.data_used,
                    },
                )
            continue

        if evaluation.zone is not Zone.UNDERPERFORMER:
            continue

        diagnosis = evaluation.diagnosis
        # Criativo fraco se corrige trocando o criativo; trocar o produto seria erro de alvo.
        if diagnosis is Diagnosis.CREATIVE_WEAK:
            recommend(
                DecisionType.KEEP,
                "product",
                str(entry.product_id),
                {
                    "action": "SWAP_CREATIVE",
                    "what": "manter o produto e trocar o criativo",
                    "why": "ROI negativo com CTR baixo aponta criativo/segmentação, não produto",
                    "diagnosis": diagnosis.value,
                    "data_used": evaluation.data_used,
                },
            )
        else:
            recommend(
                DecisionType.REPLACE,
                "product",
                str(entry.product_id),
                {
                    "action": "REPLACE_PRODUCT",
                    "what": "substituir o produto",
                    "why": "ROI negativo com amostra madura e dado liquidado",
                    "diagnosis": diagnosis.value,
                    "replacement_hint": (
                        "buscar candidato com comissão acima da mediana"
                        if diagnosis is Diagnosis.COMMISSION_INSUFFICIENT
                        else "trocar o produto, manter o criativo"
                    ),
                    "data_used": evaluation.data_used,
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
        # Ordem de entrada: maior RECEITA ESPERADA POR CLIQUE primeiro, não maior
        # Opportunity Score. O score responde "este produto é bom?"; a vaga pergunta
        # "quanto ele rende?" — e `opp_v2` satura a comissão em R$ 30, então empata um
        # produto de R$ 3 por venda com um de R$ 34 (docs/plano-10k.md §2).
        # Sem EV calculado, cai no Opportunity Score: nunca se deixa de decidir por falta
        # de um número novo.
        evs = ev_scoring.latest_evs(db)
        ranked = []
        for product in products_in_state(db, ProductState.CANDIDATE):
            score = latest_score(db, product.id)
            # Score indicativo não decide entrada.
            if product.id in in_portfolio or score is None or not score.data_available:
                continue
            if entry_guard is not None and entry_guard(product).blocked:
                result.held_brand_risk += 1
                continue
            ev = evs.get(product.id)
            ranked.append((ev.ev_per_click if ev else None, score.score, product, score, ev))
        # Quem tem EV vem antes de quem não tem: estimativa de receita vence score genérico.
        ranked.sort(
            key=lambda item: (item[0] is None, -(item[0] or 0), -item[1], item[2].id)
        )

        # Cota por categoria: pula quem estouraria a fatia da sua categoria.
        cap = category_quota.cap_per_category(
            params.max_active_products, params.max_category_share_pct
        )
        counts = category_quota.portfolio_counts(db)
        chosen = []
        for item in ranked:
            if len(chosen) >= free_slots:
                break
            category = category_quota.first_category(item[2])
            if category is not None:
                if counts[category] >= cap:
                    result.held_category_quota += 1
                    continue
                counts[category] += 1
            chosen.append(item)

        for _, _, product, score, ev in chosen:
            recommend(
                DecisionType.PROMOTE,
                "product",
                str(product.id),
                {
                    "action": "ENTER_PORTFOLIO",
                    "what": "colocar o candidato em teste (tier EXPLORATION)",
                    "why": (
                        f"{free_slots} vaga(s) de exploração livre; "
                        + (
                            f"maior receita esperada por clique (R$ {ev.ev_per_click})"
                            if ev is not None
                            else "maior Opportunity Score (sem EV calculado)"
                        )
                    ),
                    "data_used": {
                        "opportunity_score": str(score.score),
                        "algorithm_version": score.algorithm_version,
                        "daily_test_budget": str(params.min_daily_test_budget),
                        **(
                            {
                                "ev_per_click": str(ev.ev_per_click),
                                "commission_value": str(ev.commission_value),
                                "cvr_estimate": str(ev.cvr_estimate),
                                "ev_has_own_clicks": ev.data_available,
                                "ev_algorithm_version": ev.algorithm_version,
                            }
                            if ev is not None
                            else {}
                        ),
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
                "action": "RESIZE",
                "what": f"ajustar o portfólio para {sizing.recommended_size} produtos",
                "why": "tamanho que o orçamento e o CPC observado sustentam",
                "data_used": {"active_count": len(entries), "assumptions": sizing.assumptions},
            },
        )

    db.flush()
    return result
