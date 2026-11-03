"""social_posts (append-only) e oauth_tokens (mutável, por desenho)

social_posts registra o que foi efetivamente publicado — é o elo entre o pin no ar e o
clique medido em /go/. Append-only: post publicado é fato consumado.

oauth_tokens é a exceção à regra append-only do projeto, e de propósito: o refresh token
do Pinterest rotaciona a cada renovação (continuous refresh, 60 dias). Guardar cada versão
acumularia segredo em linha velha — que não audita nada e pode vazar. Uma linha por
provedor, mutável.

Revision ID: b8c0d2e4f6a7
Revises: a7b9c1d3e5f6
Create Date: 2026-11-03 09:55:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b8c0d2e4f6a7"
down_revision: str | None = "a7b9c1d3e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("creative_id", sa.BigInteger(), nullable=False),
        sa.Column("affiliate_link_id", sa.BigInteger(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("external_post_id", sa.Text(), nullable=True),
        sa.Column("post_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name=op.f("fk_social_posts_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["creative_id"], ["creatives.id"],
            name=op.f("fk_social_posts_creative_id_creatives"),
        ),
        sa.ForeignKeyConstraint(
            ["affiliate_link_id"], ["affiliate_links.id"],
            name=op.f("fk_social_posts_affiliate_link_id_affiliate_links"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_posts")),
        # Trava de idempotência: workflow re-executado não publica o mesmo criativo de novo.
        sa.UniqueConstraint("creative_id", "channel", name="uq_social_posts_creative_channel"),
    )
    op.create_index(
        "ix_social_posts_product_id_created_at", "social_posts", ["product_id", "created_at"]
    )
    op.create_index("ix_social_posts_channel_status", "social_posts", ["channel", "status"])
    op.execute("ALTER TABLE public.social_posts ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE TRIGGER social_posts_append_only
        BEFORE UPDATE OR DELETE ON social_posts
        FOR EACH ROW EXECUTE FUNCTION reject_mutation_on_append_only();
        """
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("provider", name=op.f("pk_oauth_tokens")),
    )
    op.execute("ALTER TABLE public.oauth_tokens ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_table("oauth_tokens")
    op.execute("DROP TRIGGER IF EXISTS social_posts_append_only ON social_posts;")
    op.drop_index("ix_social_posts_channel_status", table_name="social_posts")
    op.drop_index("ix_social_posts_product_id_created_at", table_name="social_posts")
    op.drop_table("social_posts")
