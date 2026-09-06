"""append-only guards and config seeds

Torna a imutabilidade do histórico uma garantia do banco, não uma promessa da
aplicação: um UPDATE ou DELETE nessas tabelas levanta exceção no Postgres.

Revision ID: 57946196c9ec
Revises: cb2d12318358
Create Date: 2026-09-06 17:10:58.368150+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "57946196c9ec"
down_revision: str | None = "cb2d12318358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY_TABLES = (
    "ai_decisions",
    "product_state_transitions",
    "product_snapshots",
    "opportunity_scores",
    "performance_scores",
    "audit_logs",
    "ad_metrics_raw",
    "conversions_raw",
    "performance_daily_revisions",
    "config_parameter_history",
    "budget_ledger",
    "llm_calls",
)

# (key, value, value_type, min, max, ai_adjustable, description)
SEED_PARAMETERS = [
    (
        "MAX_DAILY_AD_SPEND",
        100.00,
        "decimal",
        10.00,
        5000.00,
        True,
        "Teto global de investimento diário em anúncios. Nunca ultrapassado.",
    ),
    (
        "MIN_DAILY_TEST_BUDGET",
        10.00,
        "decimal",
        1.00,
        500.00,
        True,
        "Orçamento diário mínimo para um produto em teste ter chance de gerar dado.",
    ),
    (
        "MIN_ACTIVE_PRODUCTS",
        3,
        "int",
        1,
        100,
        True,
        "Piso de produtos ativos no portfólio.",
    ),
    (
        "MAX_ACTIVE_PRODUCTS",
        15,
        "int",
        1,
        100,
        True,
        "Teto de produtos ativos no portfólio.",
    ),
    (
        "EXPLORATION_PERCENTAGE",
        30,
        "int",
        0,
        100,
        True,
        "Fatia do orçamento destinada a testar produtos novos.",
    ),
    (
        "EXPLOITATION_PERCENTAGE",
        70,
        "int",
        0,
        100,
        True,
        "Fatia do orçamento destinada a escalar produtos comprovados.",
    ),
    (
        "MIN_TEST_DURATION_DAYS",
        3,
        "int",
        1,
        30,
        True,
        "Dias com dado maduro antes de cortar um produto. Não conta dia sem medição.",
    ),
    (
        "MIN_CLICKS_FOR_DECISION",
        50,
        "int",
        10,
        10000,
        True,
        "Cliques mínimos para a amostra ser considerada suficiente.",
    ),
    (
        "MIN_IMPRESSIONS_FOR_DECISION",
        1000,
        "int",
        100,
        1000000,
        True,
        "Impressões mínimas para a amostra ser considerada suficiente.",
    ),
    (
        "MIN_DATA_FOR_DECISION",
        1,
        "int",
        1,
        30,
        True,
        "Janelas de dado maduro exigidas antes de qualquer decisão destrutiva.",
    ),
    (
        "AI_AUTONOMY_LEVEL",
        1,
        "int",
        1,
        5,
        # A IA nunca ajusta o próprio nível de autonomia: seria escalada de privilégio.
        False,
        "Nível de autonomia da IA (1-5). Mesmo em 5, campanhas nascem PAUSED.",
    ),
    (
        "OPPORTUNITY_USE_LLM",
        False,
        "bool",
        None,
        None,
        False,
        "Liga o enriquecimento qualitativo por LLM no Opportunity Score.",
    ),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_mutation_on_append_only()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION
            'Tabela append-only: % em % nao e permitido', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_mutation_on_append_only();
            """
        )

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

    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")

    op.execute("DROP FUNCTION IF EXISTS reject_mutation_on_append_only();")
