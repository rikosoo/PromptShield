"""contador de limite de pedidos compartilhado entre processos

Revision ID: 0004
Revises: 0003

Idempotente (a 0001 cria as tabelas a partir dos modelos ATUAIS).
"""
from alembic import op
from lic_service.models import Base

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lic_rate_hits")
