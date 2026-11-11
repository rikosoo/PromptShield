"""regra de falta de validacao (aviso ao cliente e suspensao) por contrato e administradores do painel do fornecedor

Revision ID: 0002
Revises: 0001

Idempotente de propósito: a 0001 cria as tabelas a partir dos modelos ATUAIS, então num banco novo as colunas e a tabela já existem aqui.
"""
from alembic import op
from lic_service.models import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lic_contracts ADD COLUMN IF NOT EXISTS warn_after_days integer")
    op.execute("ALTER TABLE lic_contracts ADD COLUMN IF NOT EXISTS suspend_after_days integer")
    Base.metadata.create_all(op.get_bind(), checkfirst=True)          # cria lic_admins se ainda não existir
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_lic_admins_email_lower ON lic_admins (lower(email))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_lic_admins_email_lower")
    op.execute("DROP TABLE IF EXISTS lic_admins")
    op.execute("ALTER TABLE lic_contracts DROP COLUMN IF EXISTS suspend_after_days")
    op.execute("ALTER TABLE lic_contracts DROP COLUMN IF EXISTS warn_after_days")
