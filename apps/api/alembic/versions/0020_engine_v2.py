"""motor 2.0: achados e versao do motor guardados por analise (resultado padronizado v2) e pesos de risco por empresa

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("findings", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("analyses", sa.Column("engine_version", sa.String(10)))
    op.add_column("tenants", sa.Column("risk_weights", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("tenants", "risk_weights")
    op.drop_column("analyses", "engine_version")
    op.drop_column("analyses", "findings")
