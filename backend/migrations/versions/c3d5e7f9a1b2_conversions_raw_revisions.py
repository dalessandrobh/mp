"""conversions_raw: revisões (a tabela é append-only, então mudança vira nova linha)

Revision ID: c3d5e7f9a1b2
Revises: b2c4d6e8f0a1
Create Date: 2026-11-02 10:00:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "b2c4d6e8f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "uq_conversions_raw_order_revision"


def upgrade() -> None:
    # ADD COLUMN com default não é UPDATE: o gatilho append-only não dispara.
    op.add_column(
        "conversions_raw",
        sa.Column("revision", sa.SmallInteger(), nullable=False, server_default="1"),
    )
    # O nome da constraint antiga foi truncado pelo Postgres (limite de 63 caracteres):
    # procura pelo catálogo em vez de assumir o nome.
    old = op.get_bind().execute(sa.text(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'conversions_raw'::regclass AND contype = 'u' "
        "AND conname <> :new"
    ), {"new": NEW}).scalar_one()
    op.drop_constraint(old, "conversions_raw", type_="unique")
    op.create_unique_constraint(
        NEW, "conversions_raw",
        ["marketplace_id", "source", "external_order_id", "sub_id", "revision"],
    )


def downgrade() -> None:
    op.drop_constraint(NEW, "conversions_raw", type_="unique")
    op.create_unique_constraint(
        "uq_conversions_raw_marketplace_id_source_external_order_d00f",
        "conversions_raw", ["marketplace_id", "source", "external_order_id", "sub_id"],
    )
    op.drop_column("conversions_raw", "revision")
