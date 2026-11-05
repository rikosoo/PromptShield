"""licenciamento on-premise: estado da licença da instalação e contagem de máquinas ativas do servidor inteiro

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"


def upgrade() -> None:
    op.create_table(
        "license_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.String(64), nullable=False),
        sa.Column("auth_token", sa.Text()),
        sa.Column("serial", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("high_water", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_failed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_error", sa.String(300)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_license_state_single"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON license_state TO {APP_ROLE}")
    # a renovação informa ao fornecedor quantas máquinas estão ativas no servidor (todas as empresas): só a contagem, nenhum dado
    op.execute("""
        CREATE FUNCTION count_active_devices_all(p_cutoff timestamptz) RETURNS integer
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT count(*)::int FROM devices d LEFT JOIN api_keys k ON k.id = d.api_key_id
            WHERE d.revoked_at IS NULL AND greatest(coalesce(k.last_used_at, d.enrolled_at), d.enrolled_at) >= p_cutoff
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION count_active_devices_all(timestamptz) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION count_active_devices_all(timestamptz) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS count_active_devices_all(timestamptz)")
    op.drop_table("license_state")
