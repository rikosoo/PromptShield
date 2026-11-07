"""palavras-chave monitoradas: alerta em todo prompt que contem a palavra, com pontuacao opcional

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "keyword_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.String(100), nullable=False),
        sa.Column("whole_word", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Integer()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(300)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "term", name="uq_keyword_rules_term"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_keyword_score"),
    )
    op.execute("ALTER TABLE keyword_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE keyword_rules FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON keyword_rules USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON keyword_rules TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("keyword_rules")
