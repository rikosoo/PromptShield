"""configuração da extensão por tenant: domínios monitorados e link da política de uso

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("policy_url", sa.String(500)))
    op.add_column("tenants", sa.Column("monitored_domains", sa.ARRAY(sa.String()), nullable=False,
                                       server_default="{chatgpt.com,claude.ai}"))


def downgrade() -> None:
    op.drop_column("tenants", "monitored_domains")
    op.drop_column("tenants", "policy_url")
