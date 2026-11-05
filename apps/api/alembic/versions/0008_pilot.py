"""piloto: configuração, amostras de revisão (falso positivo)

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("pilot_started_at", sa.DateTime(timezone=True)))
    op.add_column("tenants", sa.Column("pilot_expected_users", sa.Integer()))
    op.add_column("tenants", sa.Column("pilot_days", sa.Integer(), nullable=False, server_default="30"))
    op.create_check_constraint("ck_tenants_pilot_days", "tenants", "pilot_days between 1 and 180")
    op.create_check_constraint("ck_tenants_pilot_expected", "tenants", "pilot_expected_users is null or pilot_expected_users between 1 and 1000000")
    op.create_table(
        "pilot_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_pk", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(20)),
        sa.Column("reviewer_id", sa.String(200)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_pk", name="uq_pilot_reviews_event"),  # um evento entra em uma só amostra (não conta duas vezes)
        sa.CheckConstraint("label is null or label in ('verdadeiro_positivo','falso_positivo','incerto')", name="ck_pilot_reviews_label"),
    )
    op.create_index("ix_pilot_reviews_tenant_sample", "pilot_reviews", ["tenant_id", "sample_id"])
    op.execute("ALTER TABLE pilot_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pilot_reviews FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON pilot_reviews USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pilot_reviews TO promptshield_app")


def downgrade() -> None:
    op.drop_table("pilot_reviews")
    op.drop_constraint("ck_tenants_pilot_expected", "tenants", type_="check")
    op.drop_constraint("ck_tenants_pilot_days", "tenants", type_="check")
    op.drop_column("tenants", "pilot_days")
    op.drop_column("tenants", "pilot_expected_users")
    op.drop_column("tenants", "pilot_started_at")
