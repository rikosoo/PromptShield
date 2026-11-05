"""grupos de usuarios (membros no servidor), excecoes de politica (com motivo e validade) e lista de dominios permitidos

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("user_groups", "user_group_members", "policy_exceptions", "allowlist_entries")


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "user_groups",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")), _tenant(),
        sa.Column("name", sa.String(60), nullable=False), sa.Column("description", sa.String(300)), _now("created_at"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_user_groups_name"),
    )
    op.create_table(
        "user_group_members",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")), _tenant(),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(200), nullable=False), _now("added_at"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_user", "user_group_members", ["tenant_id", "user_id"])
    op.create_table(
        "policy_exceptions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")), _tenant(),
        sa.Column("policy_id", sa.Uuid(), sa.ForeignKey("policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(200)), sa.Column("group_name", sa.String(60)),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False), _now("created_at"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revoked_by", sa.String(64)),
        sa.CheckConstraint("(user_id IS NULL) <> (group_name IS NULL)", name="ck_exception_one_target"),
    )
    op.create_index("ix_exceptions_policy", "policy_exceptions", ["tenant_id", "policy_id"])
    op.create_table(
        "allowlist_entries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")), _tenant(),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("value", sa.String(253), nullable=False),
        sa.Column("note", sa.String(300)), sa.Column("created_by", sa.String(64), nullable=False), _now("created_at"),
        sa.UniqueConstraint("tenant_id", "kind", "value", name="uq_allowlist"),
        sa.CheckConstraint("kind IN ('host')", name="ck_allowlist_kind"),
    )
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {APP_ROLE}")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
