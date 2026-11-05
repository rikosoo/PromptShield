"""copilot.com entra na lista padrão de domínios monitorados (só de quem nunca personalizou a lista)

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

OLD = ["chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com"]
NEW = [*OLD, "copilot.com"]
SET_DEFAULT_NEW = "ALTER TABLE tenants ALTER COLUMN monitored_domains SET DEFAULT '{chatgpt.com,claude.ai,gemini.google.com,copilot.microsoft.com,copilot.com}'"
SET_DEFAULT_OLD = "ALTER TABLE tenants ALTER COLUMN monitored_domains SET DEFAULT '{chatgpt.com,claude.ai,gemini.google.com,copilot.microsoft.com}'"
MOVE = "UPDATE tenants SET monitored_domains = :to WHERE monitored_domains = :frm"


def _move(frm: list[str], to: list[str]) -> None:
    op.get_bind().execute(sa.text(MOVE).bindparams(sa.bindparam("to", to, type_=sa.ARRAY(sa.String())),
                                                   sa.bindparam("frm", frm, type_=sa.ARRAY(sa.String()))))


def upgrade() -> None:
    op.execute(SET_DEFAULT_NEW)
    _move(OLD, NEW)       # listas personalizadas pelo administrador não são tocadas


def downgrade() -> None:
    op.execute(SET_DEFAULT_OLD)
    _move(NEW, OLD)
