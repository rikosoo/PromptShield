"""categorias cujo texto não é guardado (nem mascarado): saúde por padrão

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("omit_text_categories", sa.ARRAY(sa.String()), nullable=False, server_default="{saude}"))


def downgrade() -> None:
    op.drop_column("tenants", "omit_text_categories")
