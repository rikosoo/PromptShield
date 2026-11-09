"""login com e-mail e senha: hash (scrypt), troca obrigatoria, versao da senha (derruba sessoes), bloqueio por tentativas

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text()))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("password_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True)))

    # a função de login por e-mail devolve também a versão da senha e a troca obrigatória (mudar as colunas de saída exige recriar)
    op.execute("DROP FUNCTION IF EXISTS auth_user_by_email(text)")
    op.execute("""
        CREATE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid, role text, department text, groups text[], password_version int, must_change_password boolean)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT id, users.tenant_id, users.role::text, users.department::text, users.groups, users.password_version, users.must_change_password
            FROM users WHERE lower(email) = lower(p_email) AND active
        $$;
    """)
    # antes de saber a empresa: busca o necessário para conferir a senha
    op.execute("""
        CREATE FUNCTION auth_login_lookup(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid, password_hash text, password_version int, must_change_password boolean, failed_logins int, locked_until timestamptz)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT id, users.tenant_id, users.password_hash, users.password_version, users.must_change_password, users.failed_logins, users.locked_until
            FROM users WHERE lower(email) = lower(p_email) AND active
        $$;
    """)
    # registra o resultado de uma tentativa: acerto zera; erro soma e, ao passar do limite, bloqueia por p_lock_minutes
    op.execute("""
        CREATE FUNCTION auth_login_result(p_user uuid, p_ok boolean, p_max int, p_lock_minutes int)
        RETURNS timestamptz
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            UPDATE users SET
                failed_logins = CASE WHEN p_ok THEN 0 WHEN failed_logins + 1 >= p_max THEN 0 ELSE failed_logins + 1 END,
                locked_until = CASE WHEN p_ok THEN NULL WHEN failed_logins + 1 >= p_max THEN now() + make_interval(mins => p_lock_minutes) ELSE locked_until END
            WHERE id = p_user
            RETURNING locked_until
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION auth_user_by_email(text), auth_login_lookup(text), auth_login_result(uuid, boolean, int, int) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_user_by_email(text), auth_login_lookup(text), auth_login_result(uuid, boolean, int, int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_login_result(uuid, boolean, int, int)")
    op.execute("DROP FUNCTION IF EXISTS auth_login_lookup(text)")
    op.execute("DROP FUNCTION IF EXISTS auth_user_by_email(text)")
    op.execute("""
        CREATE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid, role text, department text, groups text[])
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT id, users.tenant_id, users.role::text, users.department::text, users.groups
            FROM users WHERE lower(email) = lower(p_email) AND active
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION auth_user_by_email(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_user_by_email(text) TO {APP_ROLE}")
    for c in ("password_changed_at", "locked_until", "failed_logins", "password_version", "must_change_password", "password_hash"):
        op.drop_column("users", c)
