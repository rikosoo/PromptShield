"""serviço de licenças: clientes, contratos, códigos, instalações, autorizações, nonces e auditoria

Revision ID: 0001
Revises:
"""
from alembic import op
from lic_service.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())
    op.execute("""
        CREATE FUNCTION lic_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'lic_audit é imutável (%).', TG_OP; END $$;
    """)
    op.execute("CREATE TRIGGER lic_audit_no_change BEFORE UPDATE OR DELETE ON lic_audit FOR EACH ROW EXECUTE FUNCTION lic_audit_immutable()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS lic_audit_no_change ON lic_audit")
    op.execute("DROP FUNCTION IF EXISTS lic_audit_immutable()")
    Base.metadata.drop_all(op.get_bind())
