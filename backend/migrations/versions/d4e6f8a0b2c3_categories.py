"""categories: nomes das categorias do marketplace (a API só devolve IDs)

Revision ID: d4e6f8a0b2c3
Revises: c3d5e7f9a1b2
Create Date: 2026-11-02 12:00:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c3"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Categorias de nível 1 da Shopee Brasil. A API só informa o ID: os nomes foram INFERIDOS dos
# produtos que cada categoria devolve (name_source='inferido'), não vêm da Shopee. Corrija
# pela tabela se algum estiver errado.
SHOPEE_LEVEL1 = {
    "100001": "Saúde e Bem-estar", "100009": "Acessórios de Moda", "100010": "Eletrodomésticos",
    "100011": "Moda Masculina", "100012": "Calçados", "100013": "Celulares e Acessórios",
    "100015": "Malas e Viagem", "100016": "Bolsas e Carteiras",
    "100017": "Roupas Femininas e Lingerie", "100629": "Alimentos e Bebidas",
    "100630": "Beleza", "100631": "Pet Shop", "100632": "Mãe e Bebê", "100633": "Moda Infantil",
    "100634": "Games e Consoles", "100635": "Câmeras e Segurança", "100636": "Casa e Utilidades",
    "100637": "Motos e Automotivo", "100638": "Papelaria e Escritório",
    "100639": "Hobbies e Colecionáveis", "100640": "Ferramentas e Diversos",
    "100641": "Peças de Moto", "100642": "Serviços e Outros", "100643": "Livros e Revistas",
    "100644": "Computadores e Periféricos",
}


def upgrade() -> None:
    table = op.create_table(
        "categories",
        sa.Column("marketplace", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_source", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("marketplace", "external_id", name=op.f("pk_categories")),
    )
    # Mesma regra das demais tabelas: o PostgREST do Supabase não pode ler nem escrever aqui.
    op.execute("ALTER TABLE public.categories ENABLE ROW LEVEL SECURITY;")
    op.bulk_insert(
        table,
        [
            {"marketplace": "shopee", "external_id": cid, "level": 1, "name": name,
             "name_source": "inferido"}
            for cid, name in SHOPEE_LEVEL1.items()
        ],
    )


def downgrade() -> None:
    op.drop_table("categories")
