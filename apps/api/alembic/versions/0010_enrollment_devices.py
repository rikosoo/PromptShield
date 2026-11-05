"""matrícula de dispositivos: tokens de matrícula revogáveis e uma chave própria por máquina

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    pk = lambda: sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))  # noqa: E731
    tfk = lambda: sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)  # noqa: E731
    now = lambda n="created_at": sa.Column(n, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())  # noqa: E731
    op.create_table(
        "enrollment_tokens", pk(), tfk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer()),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        now(),
    )
    op.create_table(
        "devices", pk(), tfk(),
        sa.Column("token_id", sa.Uuid(), sa.ForeignKey("enrollment_tokens.id", ondelete="SET NULL")),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_keys.id", ondelete="SET NULL")),
        sa.Column("hostname", sa.String(200), nullable=False),
        sa.Column("os", sa.String(60)),
        sa.Column("client_version", sa.String(40)),
        sa.Column("tools", sa.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        now("enrolled_at"),
    )
    op.create_index("ix_devices_tenant", "devices", ["tenant_id", "enrolled_at"])
    for t in ("enrollment_tokens", "devices"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {APP_ROLE}")
    # a máquina ainda não sabe o tenant: esta função (única que cruza tenants nesta etapa) consome UM uso do token de forma atômica
    op.execute("""
        CREATE FUNCTION enroll_consume(p_hash text) RETURNS TABLE(token_id uuid, tenant_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            UPDATE enrollment_tokens SET uses = uses + 1
            WHERE token_hash = p_hash AND revoked_at IS NULL AND expires_at > now() AND (max_uses IS NULL OR uses < max_uses)
            RETURNING id, enrollment_tokens.tenant_id
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION enroll_consume(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION enroll_consume(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS enroll_consume(text)")
    op.drop_table("devices")
    op.drop_table("enrollment_tokens")
