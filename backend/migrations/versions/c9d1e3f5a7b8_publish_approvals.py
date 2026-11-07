"""publish_approvals: decisão humana de publicar, pin a pin (append-only)

Regra 4.3 das Diretrizes de Desenvolvedor do Pinterest: o app não pode iniciar ações
automaticamente sem que a pessoa considere cada uma ("the end user must choose each Pin to
be published"). Esta tabela é onde essa escolha fica registrada. Append-only: mudar de ideia
é uma linha nova (a mais recente vale), então o histórico de quem aprovou o quê não se perde.

Revision ID: c9d1e3f5a7b8
Revises: b8c0d2e4f6a7
Create Date: 2026-11-07 12:00:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d1e3f5a7b8"
down_revision: str | None = "b8c0d2e4f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publish_approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("creative_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')",
                           name=op.f("ck_publish_approvals_decision")),
        sa.ForeignKeyConstraint(
            ["creative_id"], ["creatives.id"],
            name=op.f("fk_publish_approvals_creative_id_creatives"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name=op.f("fk_publish_approvals_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_approvals")),
    )
    op.create_index(
        "ix_publish_approvals_creative_channel_id",
        "publish_approvals",
        ["creative_id", "channel", "id"],
    )
    op.execute("ALTER TABLE public.publish_approvals ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE TRIGGER publish_approvals_append_only
        BEFORE UPDATE OR DELETE ON publish_approvals
        FOR EACH ROW EXECUTE FUNCTION reject_mutation_on_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS publish_approvals_append_only ON publish_approvals")
    op.drop_table("publish_approvals")
