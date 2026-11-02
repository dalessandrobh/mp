"""expected_values: receita esperada por clique (ev_v1), append-only

O Opportunity Score responde "este produto é bom?". A meta de comissão pergunta outra
coisa: "quanto este produto rende no slot de publicação de hoje?". Tabela própria porque a
unidade é outra — reais por clique, não 0 a 100 (docs/plano-10k.md §3).

Revision ID: a7b9c1d3e5f6
Revises: f6a8b0c2d4e5
Create Date: 2026-11-03 01:30:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a7b9c1d3e5f6"
down_revision: str | None = "f6a8b0c2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expected_values",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("ev_per_click", sa.Numeric(14, 6), nullable=False),
        sa.Column("commission_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("cvr_estimate", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvr_lower", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvr_upper", sa.Numeric(10, 6), nullable=False),
        sa.Column("alpha", sa.Numeric(12, 4), nullable=False),
        sa.Column("beta", sa.Numeric(12, 4), nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conversions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prior_source", sa.Text(), nullable=False),
        sa.Column("momentum", sa.Numeric(12, 6), nullable=True),
        sa.Column("components", JSONB(), nullable=False),
        sa.Column("data_available", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name=op.f("fk_expected_values_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expected_values")),
    )
    op.create_index(
        "ix_expected_values_product_id_computed_at", "expected_values",
        ["product_id", "computed_at"],
    )
    op.execute("ALTER TABLE public.expected_values ENABLE ROW LEVEL SECURITY;")
    # O cálculo de ontem explica a decisão de ontem: não se reescreve.
    op.execute(
        """
        CREATE TRIGGER expected_values_append_only
        BEFORE UPDATE OR DELETE ON expected_values
        FOR EACH ROW EXECUTE FUNCTION reject_mutation_on_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS expected_values_append_only ON expected_values;")
    op.drop_index("ix_expected_values_product_id_computed_at", table_name="expected_values")
    op.drop_table("expected_values")
