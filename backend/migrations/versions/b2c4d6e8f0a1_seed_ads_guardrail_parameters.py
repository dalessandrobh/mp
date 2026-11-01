"""seed ads guardrail parameters

Revision ID: b2c4d6e8f0a1
Revises: a1f3c2d4e5b6
Create Date: 2026-09-08 12:00:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b2c4d6e8f0a1"
down_revision: str | None = "a1f3c2d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Guardrails não são ajustáveis pela IA: quem afrouxa o limite é um humano.
SEED_PARAMETERS = [
    (
        "MAX_UNREVIEWED_CAMPAIGNS",
        10,
        "int",
        1,
        100,
        "Acima disso o AdsGateway aborta: há campanhas demais esperando revisão humana.",
    ),
    (
        "MAX_CAMPAIGNS_PER_EXECUTION",
        2,
        "int",
        1,
        20,
        "Campanhas que uma única execução pode criar.",
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
           false, 'system:seed')
        ON CONFLICT (key) DO NOTHING
        """
    ).bindparams(
        sa.bindparam("value", type_=JSONB),
        sa.bindparam("min_value", type_=JSONB),
        sa.bindparam("max_value", type_=JSONB),
    )
    bind = op.get_bind()
    for key, value, value_type, min_value, max_value, description in SEED_PARAMETERS:
        bind.execute(
            insert,
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "min_value": min_value,
                "max_value": max_value,
                "description": description,
            },
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM config_parameters WHERE key = ANY(:keys)"),
        {"keys": [param[0] for param in SEED_PARAMETERS]},
    )
