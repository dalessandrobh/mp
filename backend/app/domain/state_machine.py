"""Máquina de estados do funil de produtos.

CHOKE POINT: nenhum estado de produto muda fora deste módulo. Toda transição
grava uma linha append-only em `product_state_transitions` com quem mandou,
por que, e com quais números — e só então atualiza `product_current_state`.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import IllegalStateTransition
from app.domain.enums import ProductState
from app.models.funnel import ProductCurrentState, ProductStateTransition

S = ProductState

# Transições legais. O que não está aqui é proibido.
LEGAL_TRANSITIONS: dict[ProductState, frozenset[ProductState]] = {
    S.DISCOVERY: frozenset({S.QUALIFICATION, S.REJECTED, S.EXPIRED}),
    S.QUALIFICATION: frozenset({S.CANDIDATE, S.REJECTED, S.EXPIRED}),
    S.CANDIDATE: frozenset({S.TEST, S.REJECTED, S.UNDER_REVIEW, S.EXPIRED}),
    S.TEST: frozenset({S.ACTIVE, S.PAUSED, S.REJECTED, S.REPLACED, S.UNDER_REVIEW, S.EXPIRED}),
    S.ACTIVE: frozenset({S.WINNER, S.PAUSED, S.REPLACED, S.UNDER_REVIEW, S.EXPIRED}),
    # Vencedor pode perder o posto: volta para ACTIVE, não é estado absorvente.
    S.WINNER: frozenset({S.ACTIVE, S.PAUSED, S.REPLACED, S.UNDER_REVIEW, S.EXPIRED}),
    S.PAUSED: frozenset({S.ACTIVE, S.TEST, S.REJECTED, S.REPLACED, S.EXPIRED}),
    S.UNDER_REVIEW: frozenset({S.ACTIVE, S.TEST, S.PAUSED, S.REJECTED, S.REPLACED, S.EXPIRED}),
    # Terminais.
    S.REJECTED: frozenset(),
    S.REPLACED: frozenset(),
    S.EXPIRED: frozenset(),
}

# Estado de entrada de um produto recém-descoberto.
INITIAL_STATE = S.DISCOVERY

TERMINAL_STATES = frozenset({S.REJECTED, S.REPLACED, S.EXPIRED})


def is_legal(from_state: ProductState | None, to_state: ProductState) -> bool:
    """Sem estado anterior, só a entrada no funil é legal."""
    if from_state is None:
        return to_state is INITIAL_STATE
    return to_state in LEGAL_TRANSITIONS[from_state]


def assert_legal(from_state: ProductState | None, to_state: ProductState) -> None:
    if not is_legal(from_state, to_state):
        origin = from_state.value if from_state else "<novo>"
        raise IllegalStateTransition(
            f"Transição ilegal: {origin} -> {to_state.value}",
            details={"from_state": origin, "to_state": to_state.value},
        )


def get_current_state(db: Session, product_id: int) -> ProductState | None:
    return db.execute(
        select(ProductCurrentState.state).where(ProductCurrentState.product_id == product_id)
    ).scalar_one_or_none()


def transition(
    db: Session,
    *,
    product_id: int,
    to_state: ProductState,
    reason_code: str,
    actor: str,
    reason_detail: str | None = None,
    decision_id: int | None = None,
    metrics_used: dict | None = None,
) -> ProductStateTransition:
    """Única porta de entrada para mudar o estado de um produto.

    `reason_code` e `actor` são obrigatórios: nenhuma transição fica sem
    explicação nem sem responsável.
    """
    if not reason_code:
        raise IllegalStateTransition("Transição sem reason_code não é permitida")
    if not actor:
        raise IllegalStateTransition("Transição sem actor não é permitida")

    from_state = get_current_state(db, product_id)
    assert_legal(from_state, to_state)

    now = datetime.now(UTC)

    record = ProductStateTransition(
        product_id=product_id,
        from_state=from_state,
        to_state=to_state,
        reason_code=reason_code,
        reason_detail=reason_detail,
        decision_id=decision_id,
        actor=actor,
        metrics_used=metrics_used,
        created_at=now,
    )
    db.add(record)
    db.flush()

    current = db.get(ProductCurrentState, product_id)
    if current is None:
        db.add(
            ProductCurrentState(
                product_id=product_id,
                state=to_state,
                since=now,
                last_transition=record.id,
            )
        )
    else:
        current.state = to_state
        current.since = now
        current.last_transition = record.id

    db.flush()
    return record
