"""revisão humana da análise: certa, falso positivo ou faltou pegar (alimenta a medição de qualidade com dados reais)

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "event_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_pk", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("wrong_categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("missing_categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text()),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("verdict IN ('correta', 'falso_positivo', 'faltou')", name="ck_feedback_verdict"),
    )
    op.create_index("ix_feedback_tenant_verdict", "event_feedback", ["tenant_id", "verdict"])
    op.execute("ALTER TABLE event_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE event_feedback FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON event_feedback USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON event_feedback TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("event_feedback")
