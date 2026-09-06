from enum import StrEnum


class ProductState(StrEnum):
    DISCOVERY = "DISCOVERY"
    QUALIFICATION = "QUALIFICATION"
    CANDIDATE = "CANDIDATE"
    TEST = "TEST"
    ACTIVE = "ACTIVE"
    WINNER = "WINNER"
    REJECTED = "REJECTED"
    PAUSED = "PAUSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"


class PortfolioTier(StrEnum):
    EXPLORATION = "EXPLORATION"
    EXPLOITATION = "EXPLOITATION"


class DecisionType(StrEnum):
    PROMOTE = "PROMOTE"
    KEEP = "KEEP"
    REPLACE = "REPLACE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    INCREASE_BUDGET = "INCREASE_BUDGET"
    DECREASE_BUDGET = "DECREASE_BUDGET"
    REJECT = "REJECT"
    RESIZE_PORTFOLIO = "RESIZE_PORTFOLIO"
    ADJUST_PARAMETER = "ADJUST_PARAMETER"
    NO_ACTION = "NO_ACTION"


class DecisionMode(StrEnum):
    RECOMMEND = "RECOMMEND"
    EXECUTE = "EXECUTE"


class SettlementStatus(StrEnum):
    """Maturidade do dado financeiro.

    PROVISIONAL vem do ConversionReport (estimado, horas).
    SETTLED vem do ValidatedReport (comissão final, 1-7 dias).
    Só SETTLED autoriza decisão destrutiva.
    """

    PROVISIONAL = "PROVISIONAL"
    PARTIAL = "PARTIAL"
    SETTLED = "SETTLED"


class CampaignReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    SKIPPED = "SKIPPED"
