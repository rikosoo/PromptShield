"""versoes publicadas (aplicacao e pacotes de regras) e o que a instalacao informa sobre atualizacoes

Revision ID: 0003
Revises: 0002

Idempotente de propósito (a 0001 cria as tabelas a partir dos modelos ATUAIS, então num banco novo tudo isto já existe).
"""
from alembic import op
from lic_service.models import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lic_installations ADD COLUMN IF NOT EXISTS rules_version varchar(40)")
    op.execute("ALTER TABLE lic_installations ADD COLUMN IF NOT EXISTS update_state varchar(300)")
    Base.metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lic_releases")
    op.execute("ALTER TABLE lic_installations DROP COLUMN IF EXISTS update_state")
    op.execute("ALTER TABLE lic_installations DROP COLUMN IF EXISTS rules_version")
