"""BudgetGuard: CHOKE POINT de orçamento.

Nenhuma alocação é gravada em `budget_ledger` fora deste módulo. O teto vale
sobre COMMITMENT + ACTUAL - RELEASE do dia: o Meta gasta de forma assíncrona e
não dá para reservar gasto lá, então o razão interno é a única defesa. Quem
registra um ACTUAL deve liberar (RELEASE) o commitment correspondente, senão o
mesmo dinheiro conta duas vezes — erro que é conservador, nunca permissivo.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import BudgetExceeded
from app.domain import budget
from app.domain.enums import PortfolioTier
from app.models.control import BudgetLedger
from app.services.portfolio_service import PortfolioParams

LEDGER_TZ = ZoneInfo("America/Sao_Paulo")
_LOCK_KEY = "budget_guard"


def today() -> date:
    return datetime.now(LEDGER_TZ).date()


@dataclass(frozen=True)
class BudgetCheck:
    allowed: bool
    reason: str | None
    available_global: Decimal
    available_tier: Decimal


class BudgetGuard:
    def __init__(self, db: Session, params: PortfolioParams) -> None:
        self._db = db
        self._caps = budget.tier_caps(params.max_daily_ad_spend, params.exploration_percentage)

    def _used(self, day: date, scope: str | None = None) -> Decimal:
        signed = func.coalesce(
            func.sum(
                case((BudgetLedger.entry_type == "RELEASE", -BudgetLedger.amount),
                     else_=BudgetLedger.amount)
            ),
            0,
        )
        query = select(signed).select_from(BudgetLedger).where(BudgetLedger.ledger_date == day)
        if scope is not None:
            query = query.where(BudgetLedger.scope == scope)
        return Decimal(self._db.execute(query).scalar_one())

    def _lock(self) -> None:
        # Serializa checagem + gravação entre transações concorrentes; solta no fim.
        self._db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _LOCK_KEY})

    def check(
        self, amount: Decimal, tier: PortfolioTier, *, day: date | None = None
    ) -> BudgetCheck:
        self._lock()
        day = day or today()
        scope = tier.value
        used_global = self._used(day)
        used_tier = self._used(day, scope)
        avail_global = self._caps["GLOBAL"] - used_global
        avail_tier = self._caps[scope] - used_tier

        reason = None
        if amount <= 0:
            reason = "valor deve ser positivo"
        elif not budget.can_commit(self._caps["GLOBAL"], used_global, amount):
            reason = "estoura o teto global diário"
        elif not budget.can_commit(self._caps[scope], used_tier, amount):
            reason = f"estoura o teto da fatia {scope}"
        return BudgetCheck(reason is None, reason, avail_global, avail_tier)

    def commit(
        self,
        amount: Decimal,
        tier: PortfolioTier,
        *,
        product_id: int | None = None,
        campaign_id: int | None = None,
        decision_id: int | None = None,
        day: date | None = None,
    ) -> BudgetLedger:
        """Reserva orçamento. Revalida dentro do lock: o check anterior pode estar velho."""
        day = day or today()
        verdict = self.check(amount, tier, day=day)
        if not verdict.allowed:
            raise BudgetExceeded(
                f"Orçamento recusado: {verdict.reason}",
                details={"amount": str(amount), "tier": tier.value, "reason": verdict.reason},
            )
        return self._write("COMMITMENT", amount, tier, day, product_id, campaign_id, decision_id)

    def record_actual(
        self, amount: Decimal, tier: PortfolioTier, *, day: date, product_id: int | None = None,
        campaign_id: int | None = None,
    ) -> BudgetLedger:
        """Gasto real lido do Meta. Nunca recusado: o dinheiro já saiu."""
        return self._write("ACTUAL", amount, tier, day, product_id, campaign_id, None)

    def release(
        self, amount: Decimal, tier: PortfolioTier, *, day: date, product_id: int | None = None,
        campaign_id: int | None = None,
    ) -> BudgetLedger:
        return self._write("RELEASE", amount, tier, day, product_id, campaign_id, None)

    def status(self, day: date | None = None) -> dict:
        day = day or today()
        used_global = self._used(day)
        return {
            "date": day.isoformat(),
            "cap": str(self._caps["GLOBAL"]),
            "used": str(used_global),
            "available": str(self._caps["GLOBAL"] - used_global),
            "tiers": {
                tier: {
                    "cap": str(self._caps[tier]),
                    "used": str(self._used(day, tier)),
                    "available": str(self._caps[tier] - self._used(day, tier)),
                }
                for tier in ("EXPLORATION", "EXPLOITATION")
            },
        }

    def _write(self, entry_type, amount, tier, day, product_id, campaign_id, decision_id):
        row = BudgetLedger(
            ledger_date=day,
            entry_type=entry_type,
            scope=tier.value,
            product_id=product_id,
            campaign_id=campaign_id,
            amount=amount,
            decision_id=decision_id,
        )
        self._db.add(row)
        self._db.flush()
        return row
