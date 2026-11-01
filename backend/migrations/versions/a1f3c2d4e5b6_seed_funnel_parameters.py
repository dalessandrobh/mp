"""seed funnel parameters

Filtros duros da qualificação e corte de promoção a CANDIDATE. Vivem em
`config_parameters` para serem ajustáveis pelo dashboard sem novo deploy.

Revision ID: a1f3c2d4e5b6
Revises: ce194330e97c
Create Date: 2026-09-07 12:00:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1f3c2d4e5b6"
down_revision: str | None = "ce194330e97c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, value, value_type, min, max, ai_adjustable, description)
SEED_PARAMETERS = [
    (
        "QUALIFICATION_MIN_PRICE",
        10.00,
        "decimal",
        0.00,
        10000.00,
        False,
        "Preço mínimo (BRL) para um produto passar na qualificação.",
    ),
    (
        "QUALIFICATION_MIN_COMMISSION_RATE",
        0.03,
        "decimal",
        0.0,
        1.0,
        False,
        "Taxa de comissão mínima (fração: 0.03 = 3%) para qualificar.",
    ),
    (
        "QUALIFICATION_MIN_RATING",
        4.0,
        "decimal",
        0.0,
        5.0,
        False,
        "Nota mínima do produto. Só vale com avaliações suficientes.",
    ),
    (
        "QUALIFICATION_MIN_RATING_COUNT",
        10,
        "int",
        0,
        100000,
        False,
        "Avaliações necessárias para a nota ser levada em conta.",
    ),
    (
        "PROMOTION_MIN_OPPORTUNITY_SCORE",
        50.0,
        "decimal",
        0.0,
        100.0,
        True,
        "Opportunity Score mínimo (0-100) para promover QUALIFICATION -> CANDIDATE.",
    ),
]


def upgrade() -> None:
    insert = sa.text(
        """
        INSERT INTO config_parameters
          (key, value, value_type, min_value, max_value, description,
           ai_adjustable, updated_by)
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

    bind = op.get_bind()
    for key, value, value_type, min_value, max_value, ai_adjustable, description in (
        SEED_PARAMETERS
    ):
        bind.execute(
            insert,
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
