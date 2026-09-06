import pytest
from sqlalchemy import select

from app.core.exceptions import IllegalStateTransition
from app.domain import state_machine
from app.domain.enums import ProductState as S
from app.models.funnel import ProductCurrentState, ProductStateTransition


def enter_funnel(db, product_id: int) -> None:
    state_machine.transition(
        db,
        product_id=product_id,
        to_state=S.DISCOVERY,
        reason_code="DISCOVERED",
        actor="system",
    )


class TestLegality:
    def test_new_product_can_only_enter_at_discovery(self):
        assert state_machine.is_legal(None, S.DISCOVERY)
        assert not state_machine.is_legal(None, S.ACTIVE)
        assert not state_machine.is_legal(None, S.WINNER)

    def test_happy_path_of_the_funnel(self):
        path = [
            (S.DISCOVERY, S.QUALIFICATION),
            (S.QUALIFICATION, S.CANDIDATE),
            (S.CANDIDATE, S.TEST),
            (S.TEST, S.ACTIVE),
            (S.ACTIVE, S.WINNER),
        ]
        for origin, destination in path:
            assert state_machine.is_legal(origin, destination)

    def test_cannot_skip_the_funnel(self):
        assert not state_machine.is_legal(S.DISCOVERY, S.WINNER)
        assert not state_machine.is_legal(S.DISCOVERY, S.ACTIVE)
        assert not state_machine.is_legal(S.QUALIFICATION, S.TEST)

    def test_winner_can_be_demoted(self):
        assert state_machine.is_legal(S.WINNER, S.ACTIVE)

    @pytest.mark.parametrize("terminal", [S.REJECTED, S.REPLACED, S.EXPIRED])
    def test_terminal_states_have_no_exit(self, terminal):
        assert state_machine.LEGAL_TRANSITIONS[terminal] == frozenset()

    def test_every_state_has_a_transition_entry(self):
        assert set(state_machine.LEGAL_TRANSITIONS) == set(S)


class TestTransition:
    def test_transition_records_trail_and_updates_current_state(self, db, product):
        enter_funnel(db, product.id)
        record = state_machine.transition(
            db,
            product_id=product.id,
            to_state=S.QUALIFICATION,
            reason_code="PASSED_FILTERS",
            actor="ai_engine",
            metrics_used={"opportunity_score": 72.5},
        )

        current = db.get(ProductCurrentState, product.id)
        assert current.state is S.QUALIFICATION
        assert current.last_transition == record.id

        trail = db.execute(
            select(ProductStateTransition)
            .where(ProductStateTransition.product_id == product.id)
            .order_by(ProductStateTransition.id)
        ).scalars().all()
        assert [t.to_state for t in trail] == [S.DISCOVERY, S.QUALIFICATION]
        assert trail[1].from_state is S.DISCOVERY
        assert trail[1].metrics_used == {"opportunity_score": 72.5}

    def test_illegal_transition_is_rejected(self, db, product):
        enter_funnel(db, product.id)
        with pytest.raises(IllegalStateTransition):
            state_machine.transition(
                db,
                product_id=product.id,
                to_state=S.WINNER,
                reason_code="SHORTCUT",
                actor="ai_engine",
            )

    def test_illegal_transition_leaves_no_trace(self, db, product):
        enter_funnel(db, product.id)
        with pytest.raises(IllegalStateTransition):
            state_machine.transition(
                db,
                product_id=product.id,
                to_state=S.WINNER,
                reason_code="SHORTCUT",
                actor="ai_engine",
            )

        assert db.get(ProductCurrentState, product.id).state is S.DISCOVERY
        count = db.execute(
            select(ProductStateTransition).where(
                ProductStateTransition.product_id == product.id
            )
        ).scalars().all()
        assert len(count) == 1

    def test_transition_without_reason_code_is_rejected(self, db, product):
        with pytest.raises(IllegalStateTransition):
            state_machine.transition(
                db, product_id=product.id, to_state=S.DISCOVERY, reason_code="", actor="system"
            )

    def test_transition_without_actor_is_rejected(self, db, product):
        with pytest.raises(IllegalStateTransition):
            state_machine.transition(
                db,
                product_id=product.id,
                to_state=S.DISCOVERY,
                reason_code="DISCOVERED",
                actor="",
            )
