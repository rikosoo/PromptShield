"""alertas, canais de notificação, fila de envio, relatórios e agendamentos

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TABLES = ["notification_channels", "alerts", "notification_outbox", "report_schedules", "reports"]
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    uuid_pk = lambda: sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))  # noqa: E731
    tenant_fk = lambda: sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)  # noqa: E731
    now = lambda name="created_at": sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())  # noqa: E731

    op.add_column("tenants", sa.Column("volume_threshold_per_hour", sa.Integer(), nullable=False, server_default="60"))

    op.create_table(
        "notification_channels", uuid_pk(), tenant_fk(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("target", sa.String(1000), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("secret_ciphertext", sa.LargeBinary()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        now(),
        sa.CheckConstraint("kind in ('webhook','slack','teams','email','syslog_cef','siem_webhook')", name="ck_channels_kind"),
    )
    op.create_table(
        "alerts", uuid_pk(), tenant_fk(),
        sa.Column("rule", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("dedup_key", sa.String(300), nullable=False),
        sa.Column("user_id", sa.String(200), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("event_pk", sa.Uuid(), sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        now("first_seen"), now("last_seen"),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_alerts_tenant_dedup"),
    )
    op.create_index("ix_alerts_tenant_last_seen", "alerts", ["tenant_id", "last_seen"])
    op.create_table(
        "notification_outbox", uuid_pk(), tenant_fk(),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(500)),
        now(), sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("channel_id", "kind", "ref_id", name="uq_outbox_channel_ref"),
        sa.CheckConstraint("kind in ('alert','event')", name="ck_outbox_kind"),
        sa.CheckConstraint("status in ('pending','sent','failed')", name="ck_outbox_status"),
    )
    op.create_index("ix_outbox_pending", "notification_outbox", ["status", "next_attempt_at"])
    op.create_table(
        "report_schedules", uuid_pk(), tenant_fk(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("format", sa.String(5), nullable=False),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("recipients", sa.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_period_end", sa.Date()),
        now(),
        sa.CheckConstraint("kind in ('executivo','lgpd')", name="ck_schedules_kind"),
        sa.CheckConstraint("format in ('pdf','csv')", name="ck_schedules_format"),
        sa.CheckConstraint("frequency in ('mensal','semanal')", name="ck_schedules_frequency"),
    )
    op.create_table(
        "reports", uuid_pk(), tenant_fk(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("format", sa.String(5), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), sa.ForeignKey("report_schedules.id", ondelete="SET NULL")),
        now(),
    )

    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {APP_ROLE}")

    # o worker precisa saber quais tenants existem (a RLS esconde `tenants` sem app.tenant_id): só ids, nada mais.
    op.execute("""
        CREATE FUNCTION list_tenant_ids() RETURNS TABLE(tenant_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$ SELECT id FROM tenants $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION list_tenant_ids() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION list_tenant_ids() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS list_tenant_ids()")
    for t in reversed(TABLES):
        op.drop_table(t)
    op.drop_column("tenants", "volume_threshold_per_hour")
