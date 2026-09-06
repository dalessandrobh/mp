"""Num Supabase self-hosted o PostgREST publica o schema `public`.

Se alguém desligar a RLS de uma tabela, os dados de decisão e de orçamento
passam a ser legíveis por quem tiver a chave `anon`. Este teste é o alarme.
"""

from sqlalchemy import text

EXPECTED_UNPROTECTED = {"alembic_version"}


def test_every_table_has_rls_enabled(db):
    unprotected = {
        row[0]
        for row in db.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "AND NOT c.relrowsecurity"
            )
        )
    }

    assert unprotected <= EXPECTED_UNPROTECTED, (
        f"Tabelas sem RLS ficam expostas pelo PostgREST: {sorted(unprotected)}"
    )


def test_rls_does_not_lock_out_the_owner(db, product):
    """O backend é dono das tabelas, então enxerga tudo apesar da RLS.

    Se um dia alguém trocar ENABLE por FORCE sem dar BYPASSRLS à role da
    aplicação, este teste quebra antes de ir para produção.
    """
    found = db.execute(
        text("SELECT id FROM products WHERE id = :id"), {"id": product.id}
    ).scalar_one_or_none()

    assert found == product.id
