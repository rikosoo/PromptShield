"""chave de dados por tenant, retenção do texto original, expiração de chaves de API, URL de canal cifrada, relatório do piloto

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chaves de dados em tabela própria (fora de `tenants`): ler ou criar a chave nunca disputa a linha do tenant com quem a alterou
    op.create_table(
        "tenant_keys",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data_key_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE tenant_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_keys FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON tenant_keys USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
               "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON tenant_keys TO promptshield_app")
    op.add_column("tenants", sa.Column("original_retention_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("tenants", sa.Column("last_retention_run", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_tenants_original_retention", "tenants", "original_retention_days between 1 and 365")
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("notification_channels", sa.Column("target_ciphertext", sa.LargeBinary()))
    # chave expirada deixa de autenticar (rotação com período de convivência)
    op.execute("""
        CREATE OR REPLACE FUNCTION auth_api_key(p_hash text)
        RETURNS TABLE(key_id uuid, tenant_id uuid, scopes text[])
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            UPDATE api_keys SET last_used_at = now()
            WHERE key_hash = p_hash AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())
            RETURNING id, api_keys.tenant_id, api_keys.scopes
        $$;
    """)
    for t, name in (("reports", "ck_reports_kind"), ("report_schedules", "ck_schedules_kind")):
        if t == "report_schedules":
            op.drop_constraint(name, t, type_="check")
        op.create_check_constraint(name, t, "kind in ('executivo','lgpd','piloto')")


def downgrade() -> None:
    op.execute("DELETE FROM report_schedules WHERE kind = 'piloto'")  # o tipo não existia antes desta revisão
    op.execute("DELETE FROM reports WHERE kind = 'piloto'")
    op.drop_constraint("ck_schedules_kind", "report_schedules", type_="check")
    op.create_check_constraint("ck_schedules_kind", "report_schedules", "kind in ('executivo','lgpd')")
    op.drop_constraint("ck_reports_kind", "reports", type_="check")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth_api_key(p_hash text)
        RETURNS TABLE(key_id uuid, tenant_id uuid, scopes text[])
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            UPDATE api_keys SET last_used_at = now()
            WHERE key_hash = p_hash AND revoked_at IS NULL
            RETURNING id, api_keys.tenant_id, api_keys.scopes
        $$;
    """)
    op.drop_column("notification_channels", "target_ciphertext")
    op.drop_column("api_keys", "expires_at")
    op.drop_constraint("ck_tenants_original_retention", "tenants", type_="check")
    op.drop_column("tenants", "last_retention_run")
    op.drop_column("tenants", "original_retention_days")
    op.drop_table("tenant_keys")
