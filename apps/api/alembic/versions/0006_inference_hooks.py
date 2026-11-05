"""configuração e registro de requisições dos inference hooks do Claude Enterprise

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TABLES = ["inference_hook_configs", "inference_hook_requests"]
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    uuid_pk = lambda: sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))  # noqa: E731
    tenant_fk = lambda: sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)  # noqa: E731
    now = lambda name="created_at": sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())  # noqa: E731
    ts = lambda name: sa.Column(name, sa.DateTime(timezone=True))  # noqa: E731

    op.create_table(
        "inference_hook_configs", uuid_pk(), tenant_fk(),
        sa.Column("mode", sa.String(10), nullable=False, server_default="shadow"),
        sa.Column("scope", sa.String(10), nullable=False, server_default="full"),
        sa.Column("evaluate_tool_calls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secret_ciphertext", sa.LargeBinary()),
        sa.Column("previous_secret_ciphertext", sa.LargeBinary()),
        ts("previous_expires_at"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        ts("last_rejected_at"), ts("last_request_at"), ts("last_test_at"),
        now(), now("updated_at"),
        sa.UniqueConstraint("tenant_id", name="uq_hook_configs_tenant"),
        sa.CheckConstraint("mode in ('shadow','enforce')", name="ck_hook_configs_mode"),
        sa.CheckConstraint("scope in ('full','latest')", name="ck_hook_configs_scope"),
    )
    op.create_table(
        "inference_hook_requests", uuid_pk(), tenant_fk(),
        sa.Column("request_id", sa.String(200), nullable=False),
        sa.Column("frame_type", sa.String(40), nullable=False),
        sa.Column("application", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("would_deny", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocks_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_attachments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reference_id", sa.String(50)),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(200)),
        now(),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_hook_requests_tenant_request"),
    )
    op.create_index("ix_hook_requests_tenant_created", "inference_hook_requests", ["tenant_id", "created_at"])
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {APP_ROLE}")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
