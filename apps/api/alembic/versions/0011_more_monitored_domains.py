"""Gemini e Copilot na web entram na lista padrão de domínios monitorados (só de quem nunca personalizou a lista)

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

OLD = ["chatgpt.com", "claude.ai"]
NEW = ["chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com"]
SET_DEFAULT_NEW = "ALTER TABLE tenants ALTER COLUMN monitored_domains SET DEFAULT '{chatgpt.com,claude.ai,gemini.google.com,copilot.microsoft.com}'"
SET_DEFAULT_OLD = "ALTER TABLE tenants ALTER COLUMN monitored_domains SET DEFAULT '{chatgpt.com,claude.ai}'"
MOVE = "UPDATE tenants SET monitored_domains = :to WHERE monitored_domains = :frm"


def _move(frm: list[str], to: list[str]) -> None:
    op.get_bind().execute(sa.text(MOVE).bindparams(sa.bindparam("to", to, type_=sa.ARRAY(sa.String())),
                                                   sa.bindparam("frm", frm, type_=sa.ARRAY(sa.String()))))


def upgrade() -> None:
    op.execute(SET_DEFAULT_NEW)
    _move(OLD, NEW)       # só quem ainda está com a lista padrão antiga; listas personalizadas pelo administrador não são tocadas


def downgrade() -> None:
    op.execute(SET_DEFAULT_OLD)
    _move(NEW, OLD)
