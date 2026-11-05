"""licença por empresa: limite de máquinas ativas e validade; identificador (hash) da máquina para não gastar vaga ao reinstalar

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("max_devices", sa.Integer()))                       # NULL = sem limite
    op.add_column("tenants", sa.Column("license_expires_at", sa.DateTime(timezone=True)))  # NULL = sem validade
    op.create_check_constraint("ck_tenants_max_devices", "tenants", "max_devices IS NULL OR max_devices >= 0")
    op.add_column("devices", sa.Column("machine_hash", sa.String(64)))
    op.create_index("uq_devices_tenant_machine_active", "devices", ["tenant_id", "machine_hash"], unique=True,
                    postgresql_where=sa.text("machine_hash IS NOT NULL AND revoked_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_devices_tenant_machine_active", "devices")
    op.drop_column("devices", "machine_hash")
    op.drop_constraint("ck_tenants_max_devices", "tenants")
    op.drop_column("tenants", "license_expires_at")
    op.drop_column("tenants", "max_devices")
