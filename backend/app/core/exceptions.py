class DomainError(Exception):
    """Erro de regra de negócio. Vira HTTP 4xx, não 500."""

    status_code = 400
    code = "DOMAIN_ERROR"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class IllegalStateTransition(DomainError):
    status_code = 409
    code = "ILLEGAL_STATE_TRANSITION"


class BudgetExceeded(DomainError):
    status_code = 409
    code = "BUDGET_EXCEEDED"


class InsufficientData(DomainError):
    """Dado imaturo para decidir. Nunca tratamos ausência como zero."""

    status_code = 409
    code = "INSUFFICIENT_DATA"


class LockUnavailable(DomainError):
    status_code = 409
    code = "LOCK_UNAVAILABLE"


class IdempotencyConflict(DomainError):
    status_code = 409
    code = "IDEMPOTENCY_CONFLICT"


class NotFound(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class SafetyViolation(DomainError):
    """Tentativa de furar um trilho de segurança (ex.: criar campanha não-PAUSED)."""

    status_code = 403
    code = "SAFETY_VIOLATION"
