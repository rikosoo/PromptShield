"""palavras-chave: busca aproximada (erro de digitacao, plural) por palavra, ligada por padrao

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("keyword_rules", sa.Column("fuzzy", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("keyword_rules", "fuzzy")
