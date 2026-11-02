"""piso de comissão em dinheiro na qualificação

A taxa de comissão sozinha não diz nada sobre receita: 8% de R$ 22 é R$ 1,76 por venda, e
o catálogo construído por "mais vendidos" tem comissão mediana de R$ 3. Este piso impede
que produto assim ocupe o funil (docs/plano-10k.md §2).

Revision ID: f6a8b0c2d4e5
Revises: e5f7a9b1c3d4
Create Date: 2026-11-03 00:30:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f6a8b0c2d4e5"
down_revision: str | None = "e5f7a9b1c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_PARAMETERS = [
    (
        "QUALIFICATION_MIN_COMMISSION_VALUE",
        5.00,
        "decimal",
        0.00,
        1000.00,
        False,
        "Comissão mínima em dinheiro (BRL) por venda para qualificar. REJECTED é "
        "terminal: baixar este piso depois não ressuscita produto já rejeitado.",
    ),
    (
        "MAX_CATEGORY_SHARE_PCT",
        40,
        "int",
        1,
        100,
        True,
        "Fatia máxima do portfólio que uma única categoria nível 1 pode ocupar.",
    ),
]

_INSERT = sa.text(
    """
    INSERT INTO config_parameters
      (key, value, value_type, min_value, max_value, description, ai_adjustable, updated_by)
    VALUES
      (:key, :value, :value_type, :min_value, :max_value, :description,
       :ai_adjustable, 'system:seed')
    ON CONFLICT (key) DO NOTHING
    """
).bindparams(
    sa.bindparam("value", type_=JSONB),
    sa.bindparam("min_value", type_=JSONB),
    sa.bindparam("max_value", type_=JSONB),
)


def upgrade() -> None:
    bind = op.get_bind()
    for key, value, value_type, min_value, max_value, ai_adjustable, description in (
        SEED_PARAMETERS
    ):
        bind.execute(
            _INSERT,
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "min_value": min_value,
                "max_value": max_value,
                "description": description,
                "ai_adjustable": ai_adjustable,
            },
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM config_parameters WHERE key = ANY(:keys)"),
        {"keys": [param[0] for param in SEED_PARAMETERS]},
    )
