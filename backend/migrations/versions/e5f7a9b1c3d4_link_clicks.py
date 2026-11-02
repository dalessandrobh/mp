"""link_clicks: contagem de clique no redirect próprio (append-only)

A Shopee informa venda, nunca clique. Sem clique medido não há CVR e nenhum aprendizado
estatístico é possível (docs/plano-10k.md §3). O IP não é gravado: só o hash salgado.

Revision ID: e5f7a9b1c3d4
Revises: d4e6f8a0b2c3
Create Date: 2026-11-02 23:30:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d4"
down_revision: str | None = "d4e6f8a0b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "link_clicks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("affiliate_link_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("click_date", sa.Date(), nullable=False),
        sa.Column("visitor_hash", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("is_bot", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_unique", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["affiliate_link_id"], ["affiliate_links.id"],
            name=op.f("fk_link_clicks_affiliate_link_id_affiliate_links"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_link_clicks_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_link_clicks")),
    )
    op.create_index(
        "ix_link_clicks_product_id_click_date", "link_clicks", ["product_id", "click_date"]
    )
    op.create_index(
        "ix_link_clicks_dedupe", "link_clicks",
        ["affiliate_link_id", "click_date", "visitor_hash"],
    )

    # Mesma regra das demais tabelas: o PostgREST do Supabase não lê nem escreve aqui.
    op.execute("ALTER TABLE public.link_clicks ENABLE ROW LEVEL SECURITY;")

    # Histórico de tráfego não se reescreve: a função já existe desde 57946196c9ec.
    op.execute(
        """
        CREATE TRIGGER link_clicks_append_only
        BEFORE UPDATE OR DELETE ON link_clicks
        FOR EACH ROW EXECUTE FUNCTION reject_mutation_on_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS link_clicks_append_only ON link_clicks;")
    op.drop_index("ix_link_clicks_dedupe", table_name="link_clicks")
    op.drop_index("ix_link_clicks_product_id_click_date", table_name="link_clicks")
    op.drop_table("link_clicks")
