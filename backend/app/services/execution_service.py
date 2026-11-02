"""Camada EXECUTE do Decision Engine.

Transforma uma recomendação em mudança real: grava `ai_decisions`, move o
produto pela state machine e mexe no portfólio. É a única porta de execução —
RECOMMEND (`decision_engine`) só escreve recomendação.

Regras desta camada:

* **Dado de agora, não de ontem.** Antes de agir, a zona do produto é
  reavaliada. Se a recomendação envelheceu (o produto não é mais
  UNDERPERFORMER, o candidato deixou de ser candidato) ela EXPIRA em vez de
  executar.
* **Autonomia.** Execução automática exige o nível da classe de ação
  (`domain/autonomy.py`). Aprovação humana dispensa o nível, nunca as travas de
  dado nem de orçamento.
* **Tudo ou nada por recomendação.** Cada execução roda num savepoint: se
  qualquer passo falhar, nem a decisão nem o resto ficam gravados.
* **Dry-run simula de verdade.** Grava a decisão com `dry_run=true` e o que
  FARIA, mas não muda estado, portfólio nem recomendação.
* **Nunca toca o Meta.** A campanha do produto trocado segue como está (PAUSED
  por construção); se um humano a ativou, o alerta avisa para desativar.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.domain import autonomy
from app.domain.autonomy import ActionClass
from app.domain.enums import DecisionMode, DecisionType, PortfolioTier, ProductState
from app.domain.state_machine import get_current_state, transition
from app.domain.zones import Diagnosis, Zone
from app.models.ai import AiDecision, AiRecommendation
from app.models.catalog import Product
from app.models.portfolio import PortfolioProduct
from app.services import (
    alert_service,
    category_quota,
    decision_engine,
    portfolio_service,
    replacement_service,
)
from app.services.budget_guard import BudgetGuard
from app.services.opportunity_scoring import latest_score
from app.services.portfolio_service import PortfolioParams

ENGINE_VERSION = "engine_v1_execute"


class StaleRecommendation(DomainError):
    """O mundo mudou desde a recomendação: ela não vale mais."""

    status_code = 409
    code = "STALE_RECOMMENDATION"


class ExecutionBlocked(DomainError):
    """Válida, mas não executável agora (orçamento, vaga, falta de substituto)."""

    status_code = 409
    code = "EXECUTION_BLOCKED"


class ExecutionStatus(StrEnum):
    EXECUTED = "EXECUTED"
    SIMULATED = "SIMULATED"
    SKIPPED_AUTONOMY = "SKIPPED_AUTONOMY"
    SKIPPED_INFORMATIONAL = "SKIPPED_INFORMATIONAL"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ExecutionContext:
    params: PortfolioParams
    guard: BudgetGuard
    autonomy_level: int
    dry_run: bool
    actor: str
    human_approved: bool = False
    run_id: int | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    recommendation_id: int
    status: ExecutionStatus
    detail: str | None = None
    decision_id: int | None = None


@dataclass
class Plan:
    """O que será feito, decidido por leitura. `apply` é quem muda o mundo."""

    decision_type: DecisionType
    what: str
    why: str
    data_used: dict
    apply: Callable[[AiDecision], None]
    product_in: int | None = None
    product_out: int | None = None
    thresholds: dict = field(default_factory=dict)
    alternatives: list = field(default_factory=list)
    diagnosis: str | None = None


# ---------- consultas ----------


def _active_entry(db: Session, product_id: int) -> PortfolioProduct | None:
    return db.execute(
        select(PortfolioProduct).where(
            PortfolioProduct.product_id == product_id, PortfolioProduct.exited_at.is_(None)
        )
    ).scalar_one_or_none()


def _active_count(db: Session, tier: PortfolioTier | None = None) -> int:
    query = select(func.count()).select_from(PortfolioProduct).where(
        PortfolioProduct.exited_at.is_(None)
    )
    if tier is not None:
        query = query.where(PortfolioProduct.tier == tier)
    return db.execute(query).scalar_one()


def _check_entry_room(db: Session, ctx: ExecutionContext, *, freeing_exploration_slot: bool):
    """Vaga no portfólio e na fatia de exploração, com o orçamento do dia."""
    sizing = portfolio_service.sizing(db, ctx.params)
    exploration_in_use = _active_count(db, PortfolioTier.EXPLORATION) - int(
        freeing_exploration_slot
    )
    if exploration_in_use >= sizing.exploration_slots:
        raise ExecutionBlocked(
            f"sem vaga de exploração ({exploration_in_use}/{sizing.exploration_slots})"
        )
    total_after = _active_count(db) + (0 if freeing_exploration_slot else 1)
    if total_after > ctx.params.max_active_products:
        raise ExecutionBlocked(f"portfólio cheio (máximo {ctx.params.max_active_products})")

    verdict = ctx.guard.check(ctx.params.min_daily_test_budget, PortfolioTier.EXPLORATION)
    if not verdict.allowed:
        raise ExecutionBlocked(f"orçamento: {verdict.reason}")


def _check_category_quota(
    db: Session, ctx: ExecutionContext, product_id: int, *, leaving: int | None = None
) -> None:
    """A categoria do produto que entra não pode passar da fatia máxima do portfólio."""
    product = db.get(Product, product_id)
    category = category_quota.first_category(product) if product else None
    if category is None:
        return
    cap = category_quota.cap_per_category(
        ctx.params.max_active_products, ctx.params.max_category_share_pct
    )
    counts = category_quota.portfolio_counts(db, exclude={leaving} if leaving else None)
    if counts[category] >= cap:
        raise ExecutionBlocked(
            f"cota da categoria {category} cheia ({counts[category]}/{cap} do portfólio)"
        )


def _enter(db: Session, ctx: ExecutionContext, product_id: int, decision: AiDecision, reason: str):
    transition(
        db,
        product_id=product_id,
        to_state=ProductState.TEST,
        reason_code=reason,
        actor=ctx.actor,
        decision_id=decision.id,
        metrics_used={"daily_test_budget": str(ctx.params.min_daily_test_budget)},
    )
    db.add(
        PortfolioProduct(
            product_id=product_id,
            tier=PortfolioTier.EXPLORATION,
            allocated_daily_budget=ctx.params.min_daily_test_budget,
            entry_decision_id=decision.id,
        )
    )


def _require_decisive_candidate(db: Session, product_id: int) -> Decimal:
    if get_current_state(db, product_id) is not ProductState.CANDIDATE:
        raise StaleRecommendation(f"produto {product_id} não é mais CANDIDATE")
    score = latest_score(db, product_id)
    if score is None or not score.data_available:
        raise StaleRecommendation(f"produto {product_id} sem Opportunity Score decisório")
    return score.score


# ---------- planos ----------


def _plan_enter(db: Session, rec: AiRecommendation, ctx: ExecutionContext) -> Plan:
    product_id = int(rec.subject_id)
    score = _require_decisive_candidate(db, product_id)
    if _active_entry(db, product_id) is not None:
        raise StaleRecommendation(f"produto {product_id} já está no portfólio")
    _check_entry_room(db, ctx, freeing_exploration_slot=False)
    _check_category_quota(db, ctx, product_id)

    def apply(decision: AiDecision) -> None:
        _enter(db, ctx, product_id, decision, "PORTFOLIO_ENTRY")

    return Plan(
        decision_type=DecisionType.PROMOTE,
        what=rec.rationale.get("what", "entrar no portfólio"),
        why=rec.rationale.get("why", ""),
        data_used={"opportunity_score": str(score), **rec.rationale.get("data_used", {})},
        thresholds={"max_active_products": ctx.params.max_active_products},
        product_in=product_id,
        apply=apply,
    )


def _plan_graduate(db: Session, rec: AiRecommendation, ctx: ExecutionContext) -> Plan:
    product_id = int(rec.subject_id)
    entry = _active_entry(db, product_id)
    if entry is None or get_current_state(db, product_id) is not ProductState.TEST:
        raise StaleRecommendation(f"produto {product_id} não está mais em TEST no portfólio")

    evaluation = decision_engine.evaluate_entry(db, entry, ctx.params)
    if evaluation.zone is not Zone.WINNER:
        raise StaleRecommendation(f"zona atual é {evaluation.zone.value}, não WINNER")

    verdict = ctx.guard.check(entry.allocated_daily_budget, PortfolioTier.EXPLOITATION)
    if not verdict.allowed:
        raise ExecutionBlocked(f"orçamento da fatia EXPLOITATION: {verdict.reason}")

    def apply(decision: AiDecision) -> None:
        transition(
            db,
            product_id=product_id,
            to_state=ProductState.ACTIVE,
            reason_code="GRADUATED_FROM_TEST",
            actor=ctx.actor,
            decision_id=decision.id,
            metrics_used=evaluation.data_used,
        )
        entry.tier = PortfolioTier.EXPLOITATION

    return Plan(
        decision_type=DecisionType.PROMOTE,
        what="graduar de TEST para ACTIVE (tier EXPLOITATION)",
        why=rec.rationale.get("why", ""),
        data_used=evaluation.data_used,
        product_in=product_id,
        apply=apply,
    )


def _plan_replace(db: Session, rec: AiRecommendation, ctx: ExecutionContext) -> Plan:
    out_id = int(rec.subject_id)
    entry = _active_entry(db, out_id)
    if entry is None:
        raise StaleRecommendation(f"produto {out_id} não está mais no portfólio")

    evaluation = decision_engine.evaluate_entry(db, entry, ctx.params)
    if evaluation.zone is not Zone.UNDERPERFORMER:
        raise StaleRecommendation(
            f"zona atual é {evaluation.zone.value}: só UNDERPERFORMER liquidado é substituído"
        )
    diagnosis = evaluation.diagnosis or Diagnosis.INSUFFICIENT_DATA
    if diagnosis in (Diagnosis.CREATIVE_WEAK, Diagnosis.INSUFFICIENT_DATA, Diagnosis.HEALTHY):
        raise StaleRecommendation(f"diagnóstico {diagnosis.value} não justifica trocar o produto")

    cap = category_quota.cap_per_category(
        ctx.params.max_active_products, ctx.params.max_category_share_pct
    )
    full = category_quota.full_categories(
        category_quota.portfolio_counts(db, exclude={out_id}), cap
    )
    choice = replacement_service.pick_replacement(
        db, diagnosis, exclude={out_id}, blocked_categories=full
    )
    if choice.chosen is None:
        # Sem substituto não removemos ninguém: portfólio menor não é melhor.
        raise ExecutionBlocked(f"sem candidato elegível ({choice.rule})")
    in_id = choice.chosen.product_id

    _check_entry_room(
        db, ctx, freeing_exploration_slot=entry.tier is PortfolioTier.EXPLORATION
    )

    def apply(decision: AiDecision) -> None:
        reason = f"REPLACED_{diagnosis.value}"
        entry.exited_at = datetime.now(UTC)
        entry.exit_reason_code = reason
        entry.exit_decision_id = decision.id
        transition(
            db,
            product_id=out_id,
            to_state=ProductState.REPLACED,
            reason_code=reason,
            actor=ctx.actor,
            decision_id=decision.id,
            metrics_used=evaluation.data_used,
        )
        _enter(db, ctx, in_id, decision, "REPLACEMENT_ENTRY")
        alert_service.raise_alert(
            db,
            severity="INFO",
            code="PRODUCT_REPLACED",
            message=(
                f"Produto {out_id} substituído por {in_id}. Se a campanha dele foi ativada "
                "no Meta, desative-a lá: a plataforma não ativa nem desativa anúncios."
            ),
            subject_type="product",
            subject_id=str(out_id),
            details={"product_in": in_id, "diagnosis": diagnosis.value},
        )

    return Plan(
        decision_type=DecisionType.REPLACE,
        what=f"substituir o produto {out_id} pelo {in_id}",
        why=rec.rationale.get("why", ""),
        data_used=evaluation.data_used,
        thresholds={
            "min_test_duration_days": ctx.params.min_test_duration_days,
            "min_clicks": ctx.params.min_clicks_for_decision,
            "min_impressions": ctx.params.min_impressions_for_decision,
            "replacement_rule": choice.rule,
        },
        alternatives=[
            {"product_id": c.product_id, "opportunity_score": str(c.score)}
            for c in choice.alternatives
        ],
        diagnosis=diagnosis.value,
        product_in=in_id,
        product_out=out_id,
        apply=apply,
)


PLANNERS: dict[str, Callable[[Session, AiRecommendation, ExecutionContext], Plan]] = {
    "ENTER_PORTFOLIO": _plan_enter,
    "GRADUATE": _plan_graduate,
    "REPLACE_PRODUCT": _plan_replace,
}


# ---------- execução ----------


def execute(db: Session, rec: AiRecommendation, ctx: ExecutionContext) -> ExecutionOutcome:
    planner = PLANNERS.get(rec.rationale.get("action"))
    if planner is None:
        # KEEP/RESIZE e afins só informam; o humano age (ou não) por conta própria.
        return ExecutionOutcome(rec.id, ExecutionStatus.SKIPPED_INFORMATIONAL)

    if not ctx.human_approved and not autonomy.permits(
        ctx.autonomy_level, ActionClass.PORTFOLIO_CHANGE
    ):
        return ExecutionOutcome(
            rec.id,
            ExecutionStatus.SKIPPED_AUTONOMY,
            autonomy.refusal(ctx.autonomy_level, ActionClass.PORTFOLIO_CHANGE),
        )

    savepoint = db.begin_nested()
    try:
        plan = planner(db, rec, ctx)
        decision = AiDecision(
            run_id=ctx.run_id,
            recommendation_id=rec.id,
            mode=DecisionMode.EXECUTE,
            decision_type=plan.decision_type,
            autonomy_level=ctx.autonomy_level,
            dry_run=ctx.dry_run,
            subject_type="product",
            product_in=plan.product_in,
            product_out=plan.product_out,
            payload={
                "what": plan.what,
                "why": plan.why,
                "data_used": plan.data_used,
                "thresholds": plan.thresholds,
                "alternatives": plan.alternatives,
                "diagnosis": plan.diagnosis,
                "actor": ctx.actor,
                "human_approved": ctx.human_approved,
            },
            engine_version=ENGINE_VERSION,
        )
        db.add(decision)
        db.flush()

        if ctx.dry_run:
            savepoint.commit()
            return ExecutionOutcome(
                rec.id, ExecutionStatus.SIMULATED, plan.what, decision.id
            )

        plan.apply(decision)
        rec.status = "EXECUTED"
        rec.executed_decision_id = decision.id
        db.flush()
        savepoint.commit()
        return ExecutionOutcome(rec.id, ExecutionStatus.EXECUTED, plan.what, decision.id)

    except StaleRecommendation as exc:
        savepoint.rollback()
        rec.status = "EXPIRED"
        rec.rationale = {**rec.rationale, "expired_reason": exc.message}
        db.flush()
        return ExecutionOutcome(rec.id, ExecutionStatus.EXPIRED, exc.message)
    except DomainError as exc:
        savepoint.rollback()
        return ExecutionOutcome(rec.id, ExecutionStatus.BLOCKED, exc.message)
