"""tabelas multi-tenant, row-level security, papel da aplicação e funções de autenticação

Revision ID: 0002
Revises: 0001
"""
import os

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"
TENANT_TABLES = ["users", "api_keys", "policies", "events", "analyses", "incidents", "audit_log"]
TENANT_EXPR = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    password = os.environ.get("APP_DB_PASSWORD")
    if not password:
        raise RuntimeError("Defina APP_DB_PASSWORD (senha do papel da aplicação) antes de migrar.")

    # --- tenants: configurações
    op.add_column("tenants", sa.Column("store_original", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tenants", sa.Column("failure_mode", sa.String(10), nullable=False, server_default="open"))
    op.add_column("tenants", sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"))
    op.create_check_constraint("ck_tenants_failure_mode", "tenants", "failure_mode in ('open','closed')")

    uuid_pk = lambda: sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))  # noqa: E731
    tenant_fk = lambda: sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)  # noqa: E731
    now = lambda name="created_at": sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())  # noqa: E731

    op.create_table(
        "users", uuid_pk(), tenant_fk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("groups", sa.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        now(),
        sa.CheckConstraint("role in ('admin','analista','auditor','leitura')", name="ck_users_role"),
    )
    op.execute("CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))")

    op.create_table(
        "api_keys", uuid_pk(), tenant_fk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.ARRAY(sa.String()), nullable=False, server_default="{ingest}"),
        now(), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "policies", uuid_pk(), tenant_fk(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("match", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False, server_default="monitor"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        now(), now("updated_at"),
        sa.CheckConstraint("action in ('allow','mask','block','ask_justification','alert')", name="ck_policies_action"),
        sa.CheckConstraint("mode in ('monitor','enforce')", name="ck_policies_mode"),
    )

    op.create_table(
        "events", uuid_pk(), tenant_fk(),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("app", sa.String(80), nullable=False),
        sa.Column("integration_status", sa.String(20), nullable=False),
        sa.Column("user_id", sa.String(200), nullable=False),
        sa.Column("department", sa.String(120)),
        sa.Column("device_id", sa.String(200)),
        sa.Column("agent_id", sa.String(200)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("session_id", sa.String(200)),
        sa.Column("personal_account", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tool_name", sa.String(120)),
        sa.Column("masked_text", sa.Text(), nullable=False),
        sa.Column("text_length", sa.Integer(), nullable=False),
        sa.Column("original_ciphertext", sa.LargeBinary()),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_events_tenant_event"),
    )
    op.create_index("ix_events_tenant_occurred", "events", ["tenant_id", "occurred_at"])

    op.create_table(
        "analyses", uuid_pk(), tenant_fk(),
        sa.Column("event_pk", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("spans", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("would_decide", sa.String(20), nullable=False),
        sa.Column("policy_hits", sa.JSON(), nullable=False),
        sa.Column("score_version", sa.String(40), nullable=False),
        now(),
    )

    op.create_table(
        "incidents", uuid_pk(), tenant_fk(),
        sa.Column("event_pk", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="aberto"),
        sa.Column("assignee_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        now(), now("updated_at"),
        sa.CheckConstraint("severity in ('baixo','medio','alto','critico')", name="ck_incidents_severity"),
        sa.CheckConstraint("status in ('aberto','em analise','resolvido','falso positivo')", name="ck_incidents_status"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        tenant_fk(),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40)),
        sa.Column("target_id", sa.String(200)),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
    )

    # --- audit_log é append-only, até para o dono (gatilho)
    op.execute("""
        CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_log é imutável (%).', TG_OP; END $$;
    """)
    op.execute("CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
               "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()")

    # --- row-level security
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tenants USING (id = {TENANT_EXPR}) WITH CHECK (id = {TENANT_EXPR})")
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})")

    # --- papel da aplicação: sem superuser, sem BYPASSRLS
    exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}).scalar()
    verb = "ALTER" if exists else "CREATE"
    ddl = bind.execute(
        sa.text(f"SELECT format('{verb} ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %L', CAST(:pw AS text))"),
        {"pw": password},
    ).scalar()
    bind.exec_driver_sql(ddl)
    db = bind.execute(sa.text("SELECT current_database()")).scalar()
    op.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {APP_ROLE}')
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON tenants TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON users, api_keys, policies, events, analyses, incidents TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO {APP_ROLE}")

    # --- autenticação antes de saber o tenant: funções SECURITY DEFINER (únicas que cruzam tenants)
    op.execute("""
        CREATE FUNCTION auth_api_key(p_hash text)
        RETURNS TABLE(key_id uuid, tenant_id uuid, scopes text[])
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            UPDATE api_keys SET last_used_at = now()
            WHERE key_hash = p_hash AND revoked_at IS NULL
            RETURNING id, api_keys.tenant_id, api_keys.scopes
        $$;
    """)
    op.execute("""
        CREATE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid, role text, department text, groups text[])
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT id, users.tenant_id, users.role::text, users.department::text, users.groups
            FROM users WHERE lower(email) = lower(p_email) AND active
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION auth_api_key(text), auth_user_by_email(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_api_key(text), auth_user_by_email(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_api_key(text)")
    op.execute("DROP FUNCTION IF EXISTS auth_user_by_email(text)")
    for t in ["audit_log", "incidents", "analyses", "events", "policies", "api_keys", "users"]:
        op.drop_table(t)
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
    op.drop_constraint("ck_tenants_failure_mode", "tenants")
    for c in ("retention_days", "failure_mode", "store_original"):
        op.drop_column("tenants", c)
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {APP_ROLE}")
    # o papel não é removido: pode ter dependências em outros bancos do cluster
