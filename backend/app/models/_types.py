from sqlalchemy import Enum as SAEnum

from app.domain.enums import (
    CampaignReviewStatus,
    DecisionMode,
    DecisionType,
    PortfolioTier,
    ProductState,
    RunStatus,
    SettlementStatus,
)


def _pg_enum(python_enum: type, name: str) -> SAEnum:
    """Enum nativo do Postgres. Grava o .value, não o .name."""
    return SAEnum(
        python_enum,
        name=name,
        native_enum=True,
        create_type=True,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


product_state_enum = _pg_enum(ProductState, "product_state")
portfolio_tier_enum = _pg_enum(PortfolioTier, "portfolio_tier")
decision_type_enum = _pg_enum(DecisionType, "decision_type")
decision_mode_enum = _pg_enum(DecisionMode, "decision_mode")
settlement_status_enum = _pg_enum(SettlementStatus, "settlement_status")
campaign_review_status_enum = _pg_enum(CampaignReviewStatus, "campaign_review_status")
run_status_enum = _pg_enum(RunStatus, "run_status")
