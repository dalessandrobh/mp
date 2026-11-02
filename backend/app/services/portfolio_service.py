"""Leitura do portfólio e cálculo de capacidade. Nada aqui muda estado de produto."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain import formulas
from app.domain.enums import PortfolioTier, ProductState
from app.domain.portfolio_sizer import SizingInput, SizingResult, compute_sizing
from app.models.funnel import ProductCurrentState
from app.models.metrics import PerformanceDaily
from app.models.portfolio import PortfolioProduct, PortfolioSnapshot
from app.services import config_params

CPC_WINDOW_DAYS = 30


@dataclass(frozen=True)
class PortfolioParams:
    max_daily_ad_spend: Decimal
    min_daily_test_budget: Decimal
    exploration_percentage: int
    min_active_products: int
    max_active_products: int
    min_clicks_for_decision: int
    min_impressions_for_decision: int
    min_test_duration_days: int
    max_category_share_pct: int = 40


def load_params(db: Session, settings: Settings) -> PortfolioParams:
    """Parâmetro vivo do banco vence; o .env é só o ponto de partida."""
    return PortfolioParams(
        max_daily_ad_spend=config_params.get_decimal(
            db, "MAX_DAILY_AD_SPEND", settings.max_daily_ad_spend
        ),
        min_daily_test_budget=config_params.get_decimal(
            db, "MIN_DAILY_TEST_BUDGET", settings.min_daily_test_budget
        ),
        exploration_percentage=config_params.get_int(
            db, "EXPLORATION_PERCENTAGE", settings.exploration_percentage
        ),
        min_active_products=config_params.get_int(
            db, "MIN_ACTIVE_PRODUCTS", settings.min_active_products
        ),
        max_active_products=config_params.get_int(
            db, "MAX_ACTIVE_PRODUCTS", settings.max_active_products
        ),
        min_clicks_for_decision=config_params.get_int(
            db, "MIN_CLICKS_FOR_DECISION", settings.min_clicks_for_decision
        ),
        min_impressions_for_decision=config_params.get_int(
            db, "MIN_IMPRESSIONS_FOR_DECISION", settings.min_impressions_for_decision
        ),
        min_test_duration_days=config_params.get_int(
            db, "MIN_TEST_DURATION_DAYS", settings.min_test_duration_days
        ),
        max_category_share_pct=config_params.get_int(
            db, "MAX_CATEGORY_SHARE_PCT", settings.max_category_share_pct
        ),
    )


def observed_avg_cpc(db: Session, *, today: date | None = None) -> Decimal | None:
    """CPC médio ponderado da janela. Só conta dias com custo E cliques medidos."""
    since = (today or datetime.now(UTC).date()) - timedelta(days=CPC_WINDOW_DAYS)
    spend, clicks = db.execute(
        select(func.sum(PerformanceDaily.ad_spend), func.sum(PerformanceDaily.clicks)).where(
            PerformanceDaily.metric_date >= since,
            PerformanceDaily.ad_spend.is_not(None),
            PerformanceDaily.clicks.is_not(None),
        )
    ).one()
    return formulas.cpc(spend, clicks)


def active_entries(db: Session) -> list[PortfolioProduct]:
    return list(
        db.execute(
            select(PortfolioProduct)
            .where(PortfolioProduct.exited_at.is_(None))
            .order_by(PortfolioProduct.id)
        ).scalars()
    )


def sizing(db: Session, params: PortfolioParams) -> SizingResult:
    return compute_sizing(
        SizingInput(
            max_daily_ad_spend=params.max_daily_ad_spend,
            min_daily_test_budget=params.min_daily_test_budget,
            exploration_percentage=params.exploration_percentage,
            min_active_products=params.min_active_products,
            max_active_products=params.max_active_products,
            min_clicks_for_decision=params.min_clicks_for_decision,
            avg_cpc=observed_avg_cpc(db),
        )
    )


def take_snapshot(db: Session, params: PortfolioParams) -> PortfolioSnapshot:
    """Fotografia do dia. Reexecutar no mesmo dia sobrescreve a do dia."""
    entries = active_entries(db)
    result = sizing(db, params)
    winners = db.execute(
        select(func.count())
        .select_from(ProductCurrentState)
        .where(
            ProductCurrentState.state == ProductState.WINNER,
            ProductCurrentState.product_id.in_([e.product_id for e in entries] or [0]),
        )
    ).scalar_one()

    values = {
        "snapshot_date": datetime.now(UTC).date(),
        "active_count": len(entries),
        "exploration_count": sum(e.tier is PortfolioTier.EXPLORATION for e in entries),
        "exploitation_count": sum(e.tier is PortfolioTier.EXPLOITATION for e in entries),
        "winner_count": winners,
        "total_daily_budget": sum((e.allocated_daily_budget for e in entries), Decimal(0)),
        "recommended_size": result.recommended_size,
        "sizing_rationale": {
            "data_available": result.data_available,
            "range": [result.range_min, result.range_max],
            "assumptions": result.assumptions,
            "warnings": list(result.warnings),
        },
    }
    db.execute(
        insert(PortfolioSnapshot)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[PortfolioSnapshot.snapshot_date],
            set_={k: v for k, v in values.items() if k != "snapshot_date"},
        )
    )
    db.flush()
    return db.get(PortfolioSnapshot, values["snapshot_date"])
