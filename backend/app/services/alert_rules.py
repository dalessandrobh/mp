"""Regras de alerta avaliadas pelo workflow 08 do n8n (PLANNING §5.1 #12).

Alerta INFORMA; nunca age. Em especial, ROI negativo por 3 dias não pausa nada:
vira insumo para o humano e para o diagnóstico do motor (§8.1).

Idempotente por construção: o mesmo (código, assunto) não é levantado de novo
nas próximas 24h, então rodar de hora em hora não repete a notificação.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import CampaignReviewStatus, RunStatus
from app.models.ads import Campaign
from app.models.control import Alert, WorkflowRun
from app.models.metrics import PerformanceDaily
from app.services import alert_service, portfolio_service
from app.services.budget_guard import BudgetGuard
from app.services.consolidation_service import SYNC_WORKFLOW
from app.services.portfolio_service import PortfolioParams

DEDUPE_WINDOW = timedelta(hours=24)
BUDGET_WARN_RATIO = 0.9
STALE_SYNC_AFTER = timedelta(hours=12)
NEGATIVE_ROI_DAYS = 3


@dataclass
class AlertEvaluation:
    created: list[dict] = field(default_factory=list)
    skipped_duplicates: int = 0


def _already_raised(db: Session, code: str, subject_id: str | None, now: datetime) -> bool:
    return (
        db.execute(
            select(Alert.id)
            .where(
                Alert.code == code,
                Alert.subject_id.is_not_distinct_from(subject_id),
                Alert.created_at >= now - DEDUPE_WINDOW,
            )
            .limit(1)
        ).first()
        is not None
    )


def _consecutive_negative_roi(rows: list[PerformanceDaily], today) -> bool:
    if len(rows) < NEGATIVE_ROI_DAYS:
        return False
    days = [r.metric_date for r in rows]
    if days[0] < today - timedelta(days=2):
        return False  # a sequência é antiga: não é "agora"
    consecutive = all((days[i] - days[i + 1]).days == 1 for i in range(len(days) - 1))
    return consecutive and all(r.roi is not None and r.roi < 0 for r in rows)


def evaluate(
    db: Session, params: PortfolioParams, *, max_unreviewed: int, now: datetime | None = None
) -> AlertEvaluation:
    now = now or datetime.now(UTC)
    today = now.date()
    result = AlertEvaluation()

    def raise_once(severity, code, message, *, subject_type=None, subject_id=None, details=None):
        if _already_raised(db, code, subject_id, now):
            result.skipped_duplicates += 1
            return
        alert_service.raise_alert(
            db,
            severity=severity,
            code=code,
            message=message,
            subject_type=subject_type,
            subject_id=subject_id,
            details=details,
        )
        result.created.append({"severity": severity, "code": code, "message": message})

    # 1. Fila de revisão humana enchendo: o AdsGateway aborta acima do limite.
    unreviewed = db.execute(
        select(func.count())
        .select_from(Campaign)
        .where(Campaign.review_status == CampaignReviewStatus.UNREVIEWED)
    ).scalar_one()
    if unreviewed > max_unreviewed:
        raise_once(
            "CRITICAL",
            "UNREVIEWED_QUEUE_FULL",
            f"{unreviewed} campanhas aguardam revisão (limite {max_unreviewed}): "
            "a criação de campanhas está bloqueada até você revisá-las.",
            details={"unreviewed": unreviewed, "limit": max_unreviewed},
        )

    # 2. Orçamento do dia perto do teto.
    status = BudgetGuard(db, params).status()
    cap, used = float(status["cap"]), float(status["used"])
    if cap > 0 and used / cap >= BUDGET_WARN_RATIO:
        raise_once(
            "WARNING",
            "BUDGET_NEAR_CAP",
            f"Orçamento do dia em {used / cap:.0%} do teto (R$ {used:.2f} de R$ {cap:.2f}).",
            details=status,
        )

    entries = portfolio_service.active_entries(db)

    # 3. ROI negativo por 3 dias seguidos, por produto ativo.
    for entry in entries:
        rows = list(
            db.execute(
                select(PerformanceDaily)
                .where(
                    PerformanceDaily.product_id == entry.product_id,
                    PerformanceDaily.roi.is_not(None),
                )
                .order_by(PerformanceDaily.metric_date.desc())
                .limit(NEGATIVE_ROI_DAYS)
            ).scalars()
        )
        if _consecutive_negative_roi(rows, today):
            raise_once(
                "WARNING",
                "ROI_NEGATIVE_3D",
                f"Produto {entry.product_id} com ROI negativo há {NEGATIVE_ROI_DAYS} dias. "
                "Nada foi pausado: é um insumo para o diagnóstico.",
                subject_type="product",
                subject_id=str(entry.product_id),
                details={"rois": [str(r.roi) for r in rows]},
            )

    # 4. Sem performance nova: o motor estaria decidindo no escuro.
    if entries:
        last_sync = db.execute(
            select(func.max(WorkflowRun.finished_at)).where(
                WorkflowRun.workflow_name == SYNC_WORKFLOW,
                WorkflowRun.dry_run.is_(False),
                WorkflowRun.status == RunStatus.SUCCESS,
            )
        ).scalar_one()
        if last_sync is None or now - last_sync > STALE_SYNC_AFTER:
            raise_once(
                "WARNING",
                "PERFORMANCE_DATA_STALE",
                "Nenhum sync de performance bem-sucedido nas últimas 12h "
                "(o workflow 06 do n8n está rodando?).",
                details={"last_sync": last_sync.isoformat() if last_sync else None},
            )

    db.flush()
    return result
