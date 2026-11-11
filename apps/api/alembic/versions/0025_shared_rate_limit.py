"""limite de requisicoes compartilhado entre processos (so para as rotas sensiveis: login, matricula, licenca)

Revision ID: 0025
Revises: 0024

Janela fixa de 1 minuto por chave. A chave é um HASH (SHA-256) do que seria limitado (e-mail, IP): o banco nunca guarda o e-mail nem o IP em claro.
Tabela do SERVIDOR inteiro: sem tenant, sem RLS, sem dado pessoal legível. Linhas velhas são apagadas pelo próprio código.
"""
import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"


def upgrade() -> None:
    op.create_table(
        "rate_hits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("win", sa.BigInteger(), primary_key=True),
        sa.Column("n", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON rate_hits TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("rate_hits")
