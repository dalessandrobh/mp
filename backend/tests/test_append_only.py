"""A imutabilidade do histórico é garantida pelo Postgres, não pela aplicação.

Estes testes rodam contra o banco real de propósito: se alguém remover os
triggers da migration, eles quebram.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.domain import state_machine
from app.domain.enums import ProductState as S

APPEND_ONLY_SAMPLE = [
    "ai_decisions",
    "product_state_transitions",
    "audit_logs",
    "ad_metrics_raw",
    "conversions_raw",
    "budget_ledger",
]


def test_all_append_only_tables_have_the_trigger(db):
    installed = {
        row[0]
        for row in db.execute(
            text(
                "SELECT event_object_table FROM information_schema.triggers "
                "WHERE trigger_name LIKE '%_append_only'"
            )
        )
    }
    assert set(APPEND_ONLY_SAMPLE).issubset(installed)


def test_update_on_append_only_table_is_rejected(db, product):
    record = state_machine.transition(
        db,
        product_id=product.id,
        to_state=S.DISCOVERY,
        reason_code="DISCOVERED",
        actor="system",
    )

    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE product_state_transitions SET reason_code = 'FORJADO' WHERE id = :id"),
            {"id": record.id},
        )
    db.rollback()


def test_delete_on_append_only_table_is_rejected(db, product):
    record = state_machine.transition(
        db,
        product_id=product.id,
        to_state=S.DISCOVERY,
        reason_code="DISCOVERED",
        actor="system",
    )

    with pytest.raises(DatabaseError):
        db.execute(
            text("DELETE FROM product_state_transitions WHERE id = :id"), {"id": record.id}
        )
    db.rollback()


def test_campaign_cannot_be_created_active(db):
    """O trilho mais importante: campanha nasce PAUSED, e o banco recusa o resto."""
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO campaigns "
                "(platform, ad_account_id, name, objective, status, created_paused) "
                "VALUES ('meta', 'act_1', 'burlar', 'TRAFFIC', 'ACTIVE', false)"
            )
        )
    db.rollback()
