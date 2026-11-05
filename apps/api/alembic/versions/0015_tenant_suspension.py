"""suspensão reversível de uma empresa (inadimplência ou encerramento): para a coleta e as alterações, mantém os dados e a leitura

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.add_column("tenants", sa.Column("suspended_reason", sa.String(200)))
    # a autenticação ainda não sabe o tenant (sem RLS): esta função devolve só o estado de suspensão
    op.execute("""
        CREATE FUNCTION tenant_suspension(p_tenant uuid) RETURNS TABLE(suspended_at timestamptz, reason text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT t.suspended_at, t.suspended_reason::text FROM tenants t WHERE t.id = p_tenant AND t.suspended_at IS NOT NULL
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION tenant_suspension(uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION tenant_suspension(uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS tenant_suspension(uuid)")
    op.drop_column("tenants", "suspended_reason")
    op.drop_column("tenants", "suspended_at")
