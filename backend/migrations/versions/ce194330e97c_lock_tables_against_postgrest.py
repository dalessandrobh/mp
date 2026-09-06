"""lock tables against postgrest

Num Supabase self-hosted o PostgREST publica o schema `public` na internet.
Sem isto, qualquer um com a chave `anon` leria `ai_decisions`, `budget_ledger`
e todo o resto pela API REST do Supabase.

A defesa é dupla, porque uma sozinha não basta:
  1. RLS ligado sem nenhuma policy = nega tudo para quem não é dono da tabela.
  2. REVOKE em `anon` e `authenticated` = nega antes mesmo de chegar na RLS.

Repare que é ENABLE, não FORCE: no Postgres o dono da tabela não é submetido à
própria RLS. Como o backend roda as migrations e portanto é dono das tabelas,
ele continua enxergando tudo sem precisar de BYPASSRLS (que exigiria
superusuário). O `anon` do PostgREST não é dono de nada, e é justamente ele que
fica de fora.

Em Postgres puro (dev local e CI) as roles do Supabase não existem; cada passo
checa antes de agir, então a migration roda nos dois mundos.

Revision ID: ce194330e97c
Revises: 57946196c9ec
Create Date: 2026-09-06 17:20:00.000000+00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "ce194330e97c"
down_revision: str | None = "57946196c9ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Roles que o PostgREST usa para atender requisições externas.
EXPOSED_ROLES = ("anon", "authenticated")

# Lista explícita, não um "todas as tabelas do schema public": se esta migration
# for apontada por engano para o banco do próprio Supabase, ela não pode sair
# ligando RLS nas tabelas dele.
OUR_TABLES = (
    "marketplaces",
    "products",
    "product_snapshots",
    "product_state_transitions",
    "product_current_state",
    "opportunity_scores",
    "performance_scores",
    "portfolio_products",
    "portfolio_snapshots",
    "affiliate_links",
    "creatives",
    "campaigns",
    "ad_sets",
    "ads",
    "ad_metrics_raw",
    "conversions_raw",
    "performance_daily",
    "performance_daily_revisions",
    "ai_recommendations",
    "ai_decisions",
    "llm_calls",
    "config_parameters",
    "config_parameter_history",
    "budget_ledger",
    "alerts",
    "audit_logs",
    "workflow_runs",
    "idempotency_keys",
    "execution_locks",
    "simulations",
)


def upgrade() -> None:
    # RLS sem nenhuma policy: ninguém que não seja dono da tabela entra.
    for table in OUR_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")

    # Cinto e suspensório: revoga o acesso das roles expostas pelo PostgREST.
    for role in EXPOSED_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role};
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role};
                REVOKE ALL ON SCHEMA public FROM {role};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  REVOKE ALL ON TABLES FROM {role};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  REVOKE ALL ON SEQUENCES FROM {role};
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for table in OUR_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;")
    # O GRANT de volta para anon/authenticated não é refeito de propósito:
    # reabrir a leitura pública teria que ser um ato deliberado, não um rollback.
